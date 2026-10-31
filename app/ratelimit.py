"""Per-IP sliding-window rate limiter (in-process; run a single uvicorn worker)."""

import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

READ_LIMIT = int(os.getenv("RATE_LIMIT_READ", "120"))  # requests per window
WRITE_LIMIT = int(os.getenv("RATE_LIMIT_WRITE", "20"))
WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds

_hits: dict[tuple[str, bool], deque[float]] = defaultdict(deque)
_last_sweep = 0.0


# nginx must overwrite X-Real-IP with $remote_addr, otherwise clients could spoof it
def client_ip(req: Request) -> str:
    return req.headers.get("x-real-ip") or (req.client.host if req.client else "unknown")


def _sweep(now: float) -> None:
    global _last_sweep
    if now - _last_sweep < WINDOW:
        return
    _last_sweep = now
    for key in [k for k, q in _hits.items() if not q or q[-1] <= now - WINDOW]:
        del _hits[key]


async def rate_limit(req: Request) -> None:
    now = time.monotonic()
    _sweep(now)
    write = req.method not in ("GET", "HEAD", "OPTIONS")
    limit = WRITE_LIMIT if write else READ_LIMIT
    q = _hits[(client_ip(req), write)]
    while q and q[0] <= now - WINDOW:
        q.popleft()
    if len(q) >= limit:
        retry = max(1, int(q[0] + WINDOW - now) + 1)
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry)},
        )
    q.append(now)
