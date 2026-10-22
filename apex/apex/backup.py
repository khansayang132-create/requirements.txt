"""Backups of the control state: job database, autopilot policy, and plan files.

The database is copied with SQLite's online backup API, so a snapshot is consistent even while a
worker is writing. Each backup is a directory with a manifest of SHA-256 hashes; `verify` re-hashes
the files and opens the database copy. Rendered videos are not copied (they are large and
reproducible from the locked script); their paths and hashes stay in the job results.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(db: Path, out_dir: Path, extra: list[Path] = (), keep: int = 14) -> Path:
    """Write a timestamped backup under out_dir and keep only the newest `keep` backups."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = Path(out_dir) / f"apex-backup-{stamp}"
    dest.mkdir(parents=True)
    src = sqlite3.connect(db)
    dst = sqlite3.connect(dest / Path(db).name)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    for p in extra:
        if Path(p).is_file():
            shutil.copy2(p, dest / Path(p).name)
    files = {f.name: _sha(f) for f in sorted(dest.iterdir()) if f.is_file()}
    (dest / "manifest.json").write_text(json.dumps({"created": stamp, "database": Path(db).name, "files": files},
                                                   indent=2))
    old = sorted(p for p in Path(out_dir).glob("apex-backup-*") if p.is_dir())
    for p in old[:-keep] if keep > 0 else []:
        shutil.rmtree(p)
    return dest


def verify(backup_dir: Path) -> list[str]:
    """Return a list of problems; empty means the backup is intact and its database opens."""
    d = Path(backup_dir)
    try:
        manifest = json.loads((d / "manifest.json").read_text())
    except (OSError, ValueError) as e:
        return [f"manifest unreadable: {e}"]
    problems = []
    for name, digest in manifest["files"].items():
        f = d / name
        if not f.is_file():
            problems.append(f"missing {name}")
        elif _sha(f) != digest:
            problems.append(f"hash mismatch {name}")
    if not problems:
        con = sqlite3.connect(f"file:{d / manifest['database']}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problems.append("database integrity check failed")
        except sqlite3.DatabaseError as e:
            problems.append(f"database unreadable: {e}")
        finally:
            con.close()
    return problems
