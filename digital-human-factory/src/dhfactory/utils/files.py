import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_id(text: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_" else "-" for c in text.lower()).strip("-")
    if not keep:
        raise ValueError("id must contain letters or digits")
    return keep[:64]
