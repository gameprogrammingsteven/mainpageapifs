"""Private pads and temporary file uploads. Filesystem-backed; run with a single worker
(the limit checks are serialized with an in-process lock)."""

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.filetypes import check_upload

router = APIRouter(tags=["tools"])

ROOT = Path(os.getenv("TOOLS_DATA_DIR") or Path(__file__).resolve().parents[2] / "data")
PAD_DIR = ROOT / "pads"
FILE_DIR = ROOT / "files"

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PAD_BYTES = 100 * 1024
FILE_TTL = 24 * 60 * 60
PAD_TTL = 7 * 24 * 60 * 60
MAX_UPLOADS_PER_DAY = 9
MAX_PADS_PER_IP = 20

ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,32}$")
lock = asyncio.Lock()
_secret: bytes | None = None


def _now() -> int:
    return int(time.time() * 1000)


def _ensure_dirs() -> None:
    PAD_DIR.mkdir(parents=True, exist_ok=True)
    FILE_DIR.mkdir(parents=True, exist_ok=True)


def _valid_id(id_: str) -> str:
    if not ID_RE.match(id_):
        raise HTTPException(404, "Not found")
    return id_


def _new_id() -> str:
    return secrets.token_urlsafe(8)


def _secret_key() -> bytes:
    global _secret
    if _secret is None:
        _ensure_dirs()
        p = ROOT / "secret"
        if p.exists():
            _secret = p.read_bytes()
        else:
            _secret = secrets.token_hex(32).encode()
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(_secret)
    return _secret


def _hmac(value: str) -> str:
    digest = hmac.new(_secret_key(), value.encode(), hashlib.sha256).digest()
    return digest.hex()[:22]


# nginx must overwrite X-Real-IP with $remote_addr, otherwise clients could spoof it
def _client_ip(req: Request) -> str:
    return req.headers.get("x-real-ip") or (req.client.host if req.client else "unknown")


def _hash_ip(req: Request) -> str:
    return _hmac(f"ip:{_client_ip(req)}")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token_ok(token: str, owner_hash: str | None) -> bool:
    return bool(owner_hash) and hmac.compare_digest(_hash_token(token), owner_hash)


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None


# ---------- pads ----------

def _pad_meta(id_: str) -> dict | None:
    meta = _read_json(PAD_DIR / f"{id_}.json")
    if not meta or (_now() - meta["updated"]) > PAD_TTL * 1000:
        return None
    return meta


def _delete_pad(id_: str) -> None:
    for ext in ("txt", "json"):
        (PAD_DIR / f"{id_}.{ext}").unlink(missing_ok=True)


def _cleanup_pads() -> list[dict]:
    _ensure_dirs()
    live = []
    for p in PAD_DIR.glob("*.json"):
        meta = _pad_meta(p.stem)
        if meta:
            live.append(meta)
        else:
            _delete_pad(p.stem)
    return live


@router.delete("/pad", status_code=204)
async def purge_pads() -> Response:
    async with lock:
        _cleanup_pads()
    return Response(status_code=204)


@router.post("/pad")
async def create_pad(req: Request):
    ip = _hash_ip(req)
    async with lock:
        live = _cleanup_pads()
        if sum(1 for p in live if p["ip"] == ip) >= MAX_PADS_PER_IP:
            return JSONResponse({"error": f"Limit of {MAX_PADS_PER_IP} active pads reached"}, status_code=429)
        id_, token, now = _new_id(), secrets.token_urlsafe(24), _now()
        (PAD_DIR / f"{id_}.txt").write_text("", "utf-8")
        meta = {"id": id_, "created": now, "updated": now, "ownerHash": _hash_token(token), "ip": ip}
        (PAD_DIR / f"{id_}.json").write_text(json.dumps(meta), "utf-8")
    return {"id": id_, "token": token, "created": now, "updated": now}


@router.get("/pad/{id_}")
async def get_pad(id_: str) -> Response:
    _valid_id(id_)
    meta = _pad_meta(id_)
    if not meta:
        _delete_pad(id_)
        raise HTTPException(404, "Not found")
    try:
        text = (PAD_DIR / f"{id_}.txt").read_text("utf-8")
    except OSError:
        text = ""
    return Response(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store", "X-Pad-Updated": str(meta["updated"])},
    )


@router.put("/pad/{id_}", status_code=204)
async def put_pad(id_: str, req: Request) -> Response:
    _valid_id(id_)
    meta = _pad_meta(id_)
    if not meta:
        raise HTTPException(404, "Not found")
    if int(req.headers.get("content-length") or 0) > MAX_PAD_BYTES:
        raise HTTPException(413, "Too large")
    body = b""
    async for chunk in req.stream():
        body += chunk
        if len(body) > MAX_PAD_BYTES:
            raise HTTPException(413, "Too large")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Invalid text")
    updated = _now()
    async with lock:
        (PAD_DIR / f"{id_}.txt").write_text(text, "utf-8")
        (PAD_DIR / f"{id_}.json").write_text(json.dumps({**meta, "updated": updated}), "utf-8")
    return Response(status_code=204, headers={"X-Pad-Updated": str(updated)})


@router.delete("/pad/{id_}", status_code=204)
async def delete_pad(id_: str, req: Request) -> Response:
    _valid_id(id_)
    meta = _pad_meta(id_)
    if meta:
        if not _token_ok(req.headers.get("x-owner-token", ""), meta["ownerHash"]):
            raise HTTPException(403, "Forbidden")
        async with lock:
            _delete_pad(id_)
    return Response(status_code=204)


# ---------- files ----------

def _file_meta(id_: str) -> dict | None:
    return _read_json(FILE_DIR / f"{id_}.json")


def _delete_file(id_: str) -> None:
    for ext in ("bin", "json"):
        (FILE_DIR / f"{id_}.{ext}").unlink(missing_ok=True)


def _cleanup_files() -> list[dict]:
    _ensure_dirs()
    live = []
    for p in FILE_DIR.glob("*.json"):
        meta = _file_meta(p.stem)
        if meta and (_now() - meta["created"]) <= FILE_TTL * 1000:
            live.append(meta)
        else:
            _delete_file(p.stem)
    return live


def _recent_count(live: list[dict], ip: str, cid: str) -> int:
    return sum(1 for m in live if m.get("ip") == ip or m.get("cid") == cid)


@router.delete("/files", status_code=204)
async def purge_files() -> Response:
    async with lock:
        _cleanup_files()
    return Response(status_code=204)


@router.post("/files")
async def upload_file(req: Request):
    ip = _hash_ip(req)
    sent = req.headers.get("x-client-id", "")
    cid = sent if ID_RE.match(sent) else _hmac(f"cid:{_client_ip(req)}|{req.headers.get('user-agent', '')}|{secrets.token_hex(8)}")

    def limited() -> JSONResponse:
        return JSONResponse({"error": f"Limit of {MAX_UPLOADS_PER_DAY} uploads per 24 hours reached"}, status_code=429)

    def too_big() -> JSONResponse:
        return JSONResponse({"error": "File exceeds 5 MB"}, status_code=413)

    async with lock:
        if _recent_count(_cleanup_files(), ip, cid) >= MAX_UPLOADS_PER_DAY:
            return limited()

    if int(req.headers.get("content-length") or 0) > MAX_FILE_BYTES:
        return too_big()

    try:
        name = unquote(req.headers.get("x-filename", "file"))
    except Exception:
        name = "file"
    name = re.sub(r'[\\/\x00-\x1f"]', "_", name)[:120] or "file"

    body = bytearray()
    async for chunk in req.stream():
        body += chunk
        if len(body) > MAX_FILE_BYTES:
            return too_big()
    if not body:
        return JSONResponse({"error": "Empty upload"}, status_code=400)

    problem = check_upload(name, bytes(body))
    if problem:
        return JSONResponse({"error": problem}, status_code=415)

    async with lock:
        if _recent_count(_cleanup_files(), ip, cid) >= MAX_UPLOADS_PER_DAY:
            return limited()
        id_, token, created = _new_id(), secrets.token_urlsafe(24), _now()
        meta = {
            "id": id_, "name": name, "size": len(body), "created": created,
            "ip": ip, "cid": cid, "ownerHash": _hash_token(token),
        }
        (FILE_DIR / f"{id_}.bin").write_bytes(body)
        (FILE_DIR / f"{id_}.json").write_text(json.dumps(meta), "utf-8")
    return {"id": id_, "name": name, "size": len(body), "created": created, "cid": cid, "token": token}


@router.get("/files/{id_}")
async def download_file(id_: str) -> Response:
    _valid_id(id_)
    meta = _file_meta(id_)
    if not meta:
        raise HTTPException(404, "Not found")
    if (_now() - meta["created"]) > FILE_TTL * 1000:
        _delete_file(id_)
        raise HTTPException(404, "Expired")
    try:
        data = (FILE_DIR / f"{id_}.bin").read_bytes()
    except OSError:
        raise HTTPException(404, "Not found")
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(meta['name'])}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.delete("/files/{id_}", status_code=204)
async def delete_file(id_: str, req: Request) -> Response:
    _valid_id(id_)
    meta = _file_meta(id_)
    if meta:
        if not _token_ok(req.headers.get("x-owner-token", ""), meta.get("ownerHash")):
            raise HTTPException(403, "Forbidden")
        async with lock:
            _delete_file(id_)
    return Response(status_code=204)
