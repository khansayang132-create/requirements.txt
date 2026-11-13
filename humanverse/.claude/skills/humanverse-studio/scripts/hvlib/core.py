"""Production manifest: the state machine, evidence hashes, asset ownership locks, atomic writes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

STATES = ["IDEA", "RESEARCH", "DESIGN", "CHARACTER_DEVELOPMENT", "MODELING", "RIGGING", "ANIMATION", "STORYBOARD",
          "SCENE_PRODUCTION", "VOICE", "SOUND", "RENDERING", "EDITING", "QUALITY_CONTROL", "APPROVED", "DELIVERED"]
BLOCKED = "BLOCKED"


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def atomic_json(path: Path, data) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


class TransitionError(RuntimeError):
    pass


class Manifest:
    """One file per production. Every state change names its evidence; each evidence file is hashed."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"schema": 1, "state": "IDEA", "history": [], "assets": {}, "owners": {}, "created": now()}

    @property
    def state(self) -> str:
        return self.data["state"]

    def save(self) -> None:
        self.data["updated"] = now()
        atomic_json(self.path, self.data)

    def advance(self, target: str, evidence: list, note: str = "", criteria: dict | None = None) -> None:
        """Move exactly one state forward (or recover from BLOCKED to the state that was blocked)."""
        cur = self.state
        if cur == BLOCKED:
            expected = self.data.get("blocked_at")
        else:
            i = STATES.index(cur)
            expected = STATES[i + 1] if i + 1 < len(STATES) else None
        if target != expected:
            raise TransitionError(f"ILLEGAL_TRANSITION {cur} -> {target} (next allowed: {expected})")
        if criteria and not all(criteria.values()):
            failed = [k for k, v in criteria.items() if not v]
            raise TransitionError(f"ACCEPTANCE_FAILED {target}: {failed}")
        ev = []
        for p in evidence:
            p = Path(p)
            if not p.is_file() or p.stat().st_size == 0:
                raise TransitionError(f"EVIDENCE_MISSING {p}")
            ev.append({"path": str(p), "sha256": sha256(p), "bytes": p.stat().st_size})
        self.data["history"].append({"from": cur, "to": target, "at": now(), "note": note, "criteria": criteria or {}, "evidence": ev})
        self.data["state"] = target
        self.data.pop("blocked_at", None)
        self.save()

    def block(self, reason: str, at_state: str) -> None:
        self.data["history"].append({"from": self.state, "to": BLOCKED, "at": now(), "note": reason})
        self.data["blocked_at"] = at_state
        self.data["state"] = BLOCKED
        self.save()

    def register(self, kind: str, key: str, path: Path, owner: str, meta: dict | None = None) -> None:
        """Record an asset and who owns it. A different agent may not overwrite an owned asset."""
        k = f"{kind}:{key}"
        prev = self.data["owners"].get(k)
        if prev and prev != owner:
            raise TransitionError(f"OWNERSHIP {k} is owned by {prev}, not {owner}")
        self.data["owners"][k] = owner
        p = Path(path)
        self.data["assets"][k] = {"path": str(p), "sha256": sha256(p) if p.is_file() else None, "owner": owner, "at": now(), **(meta or {})}
        self.save()

    def verify_assets(self) -> list[str]:
        """Return assets whose file changed or disappeared since they were registered."""
        bad = []
        for k, a in self.data["assets"].items():
            p = Path(a["path"])
            if a.get("sha256") and (not p.is_file() or sha256(p) != a["sha256"]):
                bad.append(k)
        return bad
