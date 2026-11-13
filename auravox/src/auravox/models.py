"""Voice model manager: discovery (Piper catalog), verified downloads, registry, integrity, removal.

Catalog: https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/voices.json (sizes + MD5 per file).
Downloads are size- and MD5-verified, resumable (HTTP Range on a .part file), checked against free disk, and
refused above AVX_MAX_MODEL_MB (default 200 MB) unless approved. Every model's licence string is recorded as the
catalog states it; commercial use is never assumed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.request
from pathlib import Path

BASES = [os.environ.get("AVX_PIPER_BASE", "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"),
         "https://huggingface.co/rhasspy/piper-voices/resolve/main"]
UA = {"User-Agent": "auravox-model-manager/1.0"}


class ModelError(RuntimeError):
    pass


class ApprovalRequired(ModelError):
    pass


def md5(path: Path, chunk=1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def sha256(path: Path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


class PiperCatalog:
    def __init__(self, cache_dir: Path, bases=None, ttl: int = 86400):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.path = self.cache / "voices.json"
        self.bases = bases or BASES
        self.ttl = ttl
        self.base_used = None
        self._data = None

    def fetch(self, force=False) -> dict:
        stale = not self.path.exists() or time.time() - self.path.stat().st_mtime > self.ttl
        errors = []
        if force or stale:
            for b in self.bases:
                try:
                    with urllib.request.urlopen(urllib.request.Request(b + "/voices.json", headers=UA), timeout=30) as r:
                        data = r.read()
                    json.loads(data)
                    self.path.write_bytes(data)
                    self.base_used = b
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{b}: {type(e).__name__}: {e}")
            if not self.path.exists():
                raise ModelError("cannot fetch the Piper catalog: " + " | ".join(errors))
        self.base_used = self.base_used or self.bases[0]
        self._data = json.loads(self.path.read_text())
        return self._data

    @property
    def data(self) -> dict:
        return self._data if self._data is not None else self.fetch()

    def voices(self, lang: str | None = None, quality: str | None = None, name: str | None = None):
        for key, v in sorted(self.data.items()):
            lg = v.get("language", {})
            code = lg.get("code") or key.split("-")[0]
            if lang and not (code == lang or code.startswith(lang + "_") or lg.get("family") == lang):
                continue
            if quality and v.get("quality") != quality:
                continue
            if name and name.lower() not in key.lower():
                continue
            parts = key.split("-")
            yield {"key": key, "lang_code": code, "lang_family": lg.get("family", code.split("_")[0]),
                   "language": lg.get("name_english", code), "name": v.get("name") or (parts[1] if len(parts) > 1 else key),
                   "quality": v.get("quality", "unknown"), "num_speakers": v.get("num_speakers", 1),
                   "speaker_id_map": v.get("speaker_id_map", {}), "files": v.get("files", {}),
                   "license": v.get("license") or "see MODEL_CARD", "aliases": v.get("aliases", [])}

    def get(self, key: str) -> dict | None:
        return next((v for v in self.voices() if v["key"] == key), None)

    def languages(self) -> list[tuple[str, str]]:
        return sorted({(v["lang_code"], v["language"]) for v in self.voices()})

    def stats(self) -> dict:
        q: dict[str, int] = {}
        for v in self.voices():
            q[v["quality"]] = q.get(v["quality"], 0) + 1
        return {"voices": len(self.data), "languages": len(self.languages()), "qualities": q}


class ModelStore:
    def __init__(self, db, root: Path):
        self.db = db
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = PiperCatalog(self.root / ".catalog")
        self.max_mb = float(os.environ.get("AVX_MAX_MODEL_MB", "200"))

    # ---------------------------------------------------------------- registry
    def installed(self, engine: str | None = None) -> list[dict]:
        rows = self.db.q("SELECT * FROM models WHERE status = 'PASS'" + (" AND engine = ?" if engine else ""), (engine,) if engine else ())
        return rows

    def get(self, key: str) -> dict | None:
        return self.db.one("SELECT * FROM models WHERE key = ?", (key,))

    def disk_free_mb(self) -> float:
        return shutil.disk_usage(self.root).free / 1e6

    # ---------------------------------------------------------------- download
    def _download(self, url: str, dest: Path, size: int, digest: str, progress=print, retries: int = 3) -> None:
        part = dest.with_name(dest.name + ".part")
        for attempt in range(1, retries + 1):
            try:
                have = part.stat().st_size if part.exists() else 0
                hdr = dict(UA, **({"Range": f"bytes={have}-"} if have else {}))
                with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=120) as r:
                    mode = "ab" if have and r.status == 206 else "wb"
                    with open(part, mode) as f:
                        shutil.copyfileobj(r, f, 1 << 20)
                if size and part.stat().st_size != size:
                    raise ModelError(f"size {part.stat().st_size} != {size}")
                if digest and md5(part) != digest:
                    part.unlink()
                    raise ModelError("md5 mismatch (corrupt download discarded)")
                os.replace(part, dest)
                return
            except Exception as e:  # noqa: BLE001
                progress(f"  attempt {attempt} failed: {type(e).__name__}: {e}")
                if attempt == retries:
                    raise ModelError(f"download failed after {retries} attempts: {url}: {e}") from e
                time.sleep(min(2 ** attempt, 10))

    def install(self, key: str, approve: bool = False, progress=print) -> dict:
        v = self.catalog.get(key)
        if not v:
            raise ModelError(f"VOICE_NOT_FOUND {key} (not in the Piper catalog)")
        files = {Path(p).name: (p, i.get("size_bytes", 0), i.get("md5_digest", "")) for p, i in v["files"].items() if not p.endswith("MODEL_CARD")}
        total = sum(s for _p, s, _m in files.values()) / 1e6
        if total > self.max_mb and not approve:
            raise ApprovalRequired(f"{key} is {total:.0f} MB > {self.max_mb:.0f} MB; re-run with approval")
        if total * 1.2 > self.disk_free_mb():
            raise ModelError(f"not enough disk: need {total:.0f} MB, free {self.disk_free_mb():.0f} MB")
        d = self.root / "piper" / key
        d.mkdir(parents=True, exist_ok=True)
        base = self.catalog.base_used or BASES[0]
        for name, (p, size, digest) in files.items():
            dest = d / name
            if dest.exists() and (not size or dest.stat().st_size == size) and (not digest or md5(dest) == digest):
                progress(f"  cached {name}")
                continue
            progress(f"  downloading {name} ({size / 1e6:.1f} MB)")
            self._download(f"{base}/{p}", dest, size, digest, progress)
        card = next((p for p in v["files"] if p.endswith("MODEL_CARD")), None)
        lic = v["license"]
        if card:
            try:
                with urllib.request.urlopen(urllib.request.Request(f"{base}/{card}", headers=UA), timeout=30) as r:
                    txt = r.read().decode("utf-8", "replace")
                (d / "MODEL_CARD").write_text(txt)
                lic = next((ln.split(":", 1)[1].strip() for ln in txt.splitlines() if ln.lower().strip("* -").startswith("license")), lic)
            except Exception:  # noqa: BLE001
                pass
        onnx = next(d / n for n in files if n.endswith(".onnx"))
        cfg = next((d / n for n in files if n.endswith(".onnx.json")), None)
        self.db.insert("models", {"key": key, "engine": "piper", "path": str(onnx), "config_path": str(cfg) if cfg else None,
                                  "sha256": sha256(onnx), "bytes": sum((d / n).stat().st_size for n in files), "license": lic, "status": "PASS",
                                  "installed_at": time.time(),
                                  "meta": {"lang_code": v["lang_code"], "quality": v["quality"], "num_speakers": v["num_speakers"],
                                           "speakers": v["speaker_id_map"], "source": base}})
        return self.get(key)

    def verify(self, key: str) -> dict:
        m = self.get(key)
        if not m:
            return {"key": key, "status": "NOT INSTALLED"}
        p = Path(m["path"])
        ok = p.is_file() and sha256(p) == m["sha256"]
        self.db.update("models", "key", key, status="PASS" if ok else "FAIL")
        return {"key": key, "status": "PASS" if ok else "FAIL", "path": str(p)}

    def remove(self, key: str) -> bool:
        m = self.get(key)
        if not m:
            return False
        shutil.rmtree(Path(m["path"]).parent, ignore_errors=True)
        self.db.update("models", "key", key, status="REMOVED")
        return True
