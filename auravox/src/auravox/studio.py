"""The studio: one object that holds the database, engines, model store and folders. Everything else uses it."""

from __future__ import annotations

import os
import time
from pathlib import Path

from .db import DB
from .engines.espeak import EspeakEngine
from .engines.piper import PiperEngine
from .models import ModelStore


class Studio:
    def __init__(self, home: Path | str | None = None):
        self.home = Path(home or os.environ.get("AVX_HOME", Path.cwd() / "data")).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.db = DB(self.home / "auravox.db")
        self.store = ModelStore(self.db, self.home / "models")
        self.engines = {"espeak-ng": EspeakEngine(), "piper": PiperEngine(self.store)}
        for d in ("takes", "rejected", "productions", "auditions", "exports"):
            (self.home / d).mkdir(exist_ok=True)

    def engine_health(self, name: str, max_age: float = 600) -> tuple[str, str]:
        r = self.db.one("SELECT * FROM engines WHERE name = ?", (name,))
        if r and time.time() - (r["checked_at"] or 0) < max_age:
            return r["status"], r["detail"]
        st, detail = self.engines[name].health()
        caps = {}
        try:
            caps = self.engines[name].capabilities()
            caps["languages_count"] = len(caps.get("languages", []))
            caps["languages"] = caps["languages"][:200]
        except Exception as e:  # noqa: BLE001
            caps = {"error": str(e)}
        self.db.insert("engines", {"name": name, "status": st, "detail": detail, "capabilities": caps, "checked_at": time.time()})
        return st, detail

    def refresh_engines(self) -> dict:
        return {n: self.engine_health(n, max_age=0) for n in self.engines}
