"""Upload allow-list: extension must be listed AND the content must match its kind."""

EXT: dict[str, str] = {
    # images
    "png": "png", "jpg": "jpg", "jpeg": "jpg", "gif": "gif", "webp": "webp", "bmp": "bmp", "ico": "ico",
    "tif": "tiff", "tiff": "tiff", "heic": "isobmff", "heif": "isobmff", "avif": "isobmff",
    # documents (macro-free only)
    "pdf": "pdf", "docx": "zip", "xlsx": "zip", "pptx": "zip", "odt": "zip", "ods": "zip", "odp": "zip",
    "epub": "zip", "rtf": "rtf",
    # audio
    "mp3": "mp3", "aac": "aac", "m4a": "isobmff", "wav": "wav", "ogg": "ogg", "oga": "ogg", "opus": "ogg",
    "flac": "flac", "mid": "midi", "midi": "midi",
    # video
    "mp4": "isobmff", "m4v": "isobmff", "mov": "isobmff", "3gp": "isobmff", "avi": "avi",
    "webm": "matroska", "mkv": "matroska",
    # plain text
    "txt": "text", "md": "text", "csv": "text", "tsv": "text", "json": "text", "log": "text", "srt": "text",
    "vtt": "text", "yaml": "text", "yml": "text", "toml": "text", "ini": "text",
}


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _matches(kind: str, b: bytes) -> bool:
    if kind == "png":
        return b.startswith(b"\x89PNG\r\n\x1a\n")
    if kind == "jpg":
        return b.startswith(b"\xff\xd8\xff")
    if kind == "gif":
        return b.startswith((b"GIF87a", b"GIF89a"))
    if kind == "webp":
        return b.startswith(b"RIFF") and b[8:12] == b"WEBP"
    if kind == "bmp":
        return b.startswith(b"BM")
    if kind == "ico":
        return b.startswith(b"\x00\x00\x01\x00")
    if kind == "tiff":
        return b.startswith((b"II*\x00", b"MM\x00*"))
    if kind == "isobmff":
        return b[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip")
    if kind == "pdf":
        return b.startswith(b"%PDF-")
    if kind == "zip":
        return b.startswith(b"PK\x03\x04")
    if kind == "rtf":
        return b.startswith(b"{\\rtf")
    if kind == "mp3":
        return b.startswith(b"ID3") or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0)
    if kind == "aac":
        return len(b) > 1 and b[0] == 0xFF and (b[1] & 0xF6) == 0xF0
    if kind == "wav":
        return b.startswith(b"RIFF") and b[8:12] == b"WAVE"
    if kind == "avi":
        return b.startswith(b"RIFF") and b[8:12] == b"AVI "
    if kind == "ogg":
        return b.startswith(b"OggS")
    if kind == "flac":
        return b.startswith(b"fLaC")
    if kind == "midi":
        return b.startswith(b"MThd")
    if kind == "matroska":
        return b.startswith(b"\x1a\x45\xdf\xa3")
    if kind == "text":
        return b"\x00" not in b[:8192] and not b.startswith((b"MZ", b"#!"))
    return False


def check_upload(name: str, data: bytes) -> str | None:
    """Returns an error message, or None if the file is acceptable."""
    ext = ext_of(name)
    if "." not in name or ext not in EXT:
        return "This file type is not allowed"
    kind = EXT[ext]
    if not _matches(kind, data):
        return "File contents do not match its type"
    if kind == "zip" and b"vbaProject" in data:
        return "Macro-enabled documents are not allowed"
    return None
