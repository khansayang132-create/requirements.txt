"""Central intelligence orchestrator.

One production = one row plus one checkpoint row per stage. Stages run in order; each reads the
outputs of the stages before it and writes its own. A failed stage is retried when the error is
transient (the LLM or a network call); otherwise the production stops as failed and can be
resumed later, skipping every stage that already succeeded. A production is "completed" only
after quality assurance passed on the final files."""
from __future__ import annotations

import os
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .. import audio as A
from ..config import Settings
from ..llm import LLMClient, LLMEmpty
from ..mastering import integrated_loudness, limit
from ..pipeline import generate
from ..profiles import PRESETS, ProfileStore
from . import creative, emotion, lab, mix, qa, scriptgen, subtitles, voice
from .db import Store, dumps, loads, new_id, now

STAGES = ["intent", "concepts", "script", "analysis", "enhancement", "emotion", "voice", "audio", "subtitles",
          "qa", "deliver"]
TRANSIENT = (LLMEmpty, ConnectionError, TimeoutError)
MAX_ATTEMPTS = 3


class StageError(RuntimeError):
    pass


class Orchestrator:
    def __init__(self, settings: Settings, profiles: ProfileStore, store: Store) -> None:
        self.settings, self.profiles, self.db = settings, profiles, store
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nova-production")
        self.out_root = settings.outputs_dir / "productions"

    def llm(self) -> LLMClient | None:
        return LLMClient.from_settings(self.settings)

    # --- public API -----------------------------------------------------------------------
    def create(self, request: dict, idempotency_key: str | None = None, job_run_id: str | None = None) -> dict:
        if not (request.get("idea") or request.get("script")):
            raise ValueError("an idea or a script is required")
        if idempotency_key:
            existing = self.db.one("SELECT id FROM productions WHERE idempotency_key=?", (idempotency_key,))
            if existing:
                return self.get(existing["id"]) | {"duplicate": True}
        pid = new_id()
        self.db.insert("productions", {"id": pid, "idea": (request.get("idea") or "")[:2000], "request": dumps(request),
                                       "status": "queued", "current_stage": None, "idempotency_key": idempotency_key,
                                       "job_run_id": job_run_id, "created_at": now(), "updated_at": now()})
        for st in STAGES:
            self.db.insert("production_stages", {"production_id": pid, "stage": st, "status": "pending"})
        self.db.log(pid, "production created")
        return self.get(pid)

    def submit(self, pid: str):
        return self.pool.submit(self.run, pid)

    def get(self, pid: str) -> dict:
        p = self.db.one("SELECT * FROM productions WHERE id=?", (pid,))
        if not p:
            raise KeyError(pid)
        p["request"] = loads(p["request"])
        p["stages"] = [dict(s, output=loads(s["output"])) for s in self.db.all(
            "SELECT * FROM production_stages WHERE production_id=? ORDER BY rowid", (pid,))]
        p["assets"] = self.db.all("SELECT * FROM audio_assets WHERE production_id=?", (pid,))
        p["subtitles"] = self.db.all("SELECT * FROM subtitles WHERE production_id=?", (pid,))
        q = self.db.one("SELECT * FROM quality_reports WHERE production_id=?", (pid,))
        p["qa"] = dict(q, report=loads(q["report"])) if q else None
        p["qa_passed"] = bool(q and q["passed"])
        return p

    def list(self, limit: int = 50) -> list[dict]:
        return self.db.all("SELECT id, idea, status, current_stage, error, created_at, updated_at FROM productions "
                           "ORDER BY created_at DESC LIMIT ?", (limit,))

    def logs(self, pid: str) -> list[dict]:
        return self.db.all("SELECT ts, level, stage, message FROM production_logs WHERE production_id=? ORDER BY id", (pid,))

    def resume(self, pid: str) -> dict:
        p = self.get(pid)
        if p["status"] in ("running", "completed"):
            raise ValueError(f"production is {p['status']}")
        self.db.execute("UPDATE productions SET status='queued', error=NULL, updated_at=? WHERE id=?", (now(), pid))
        self.db.log(pid, "resume requested")
        return self.get(pid)

    def run(self, pid: str) -> dict:
        self.db.execute("UPDATE productions SET status='running', updated_at=? WHERE id=?", (now(), pid))
        ctx = {s["stage"]: loads(s["output"]) for s in self.db.all(
            "SELECT stage, output FROM production_stages WHERE production_id=? AND status='done'", (pid,))}
        req = loads(self.db.one("SELECT request FROM productions WHERE id=?", (pid,))["request"])
        for st in STAGES:
            row = self.db.one("SELECT status, attempts FROM production_stages WHERE production_id=? AND stage=?", (pid, st))
            if row["status"] == "done":
                continue
            self.db.execute("UPDATE productions SET current_stage=?, updated_at=? WHERE id=?", (st, now(), pid))
            attempts = row["attempts"]
            while True:
                attempts += 1
                self.db.execute("UPDATE production_stages SET status='running', attempts=?, started_at=?, error=NULL "
                                "WHERE production_id=? AND stage=?", (attempts, now(), pid, st))
                self.db.log(pid, f"stage {st} started (attempt {attempts})", stage=st)
                try:
                    out = getattr(self, f"_stage_{st}")(pid, req, ctx)
                    ctx[st] = out
                    self.db.execute("UPDATE production_stages SET status='done', output=?, finished_at=? WHERE "
                                    "production_id=? AND stage=?", (dumps(out), now(), pid, st))
                    self.db.log(pid, f"stage {st} done", stage=st)
                    break
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    transient = isinstance(exc, TRANSIENT) or "httpx" in type(exc).__module__
                    self.db.log(pid, msg + ("" if transient else "\n" + traceback.format_exc()[-1500:]), "error", st)
                    if transient and attempts < MAX_ATTEMPTS:
                        continue
                    self.db.execute("UPDATE production_stages SET status='failed', error=?, finished_at=? WHERE "
                                    "production_id=? AND stage=?", (msg[:2000], now(), pid, st))
                    self.db.execute("UPDATE productions SET status='failed', error=?, updated_at=? WHERE id=?",
                                    (f"{st}: {msg}"[:2000], now(), pid))
                    self.db.notify(f"Production failed at {st}: {msg}"[:500], "error", production_id=pid)
                    return self.get(pid)
        qa_ok = bool(ctx.get("qa", {}).get("passed"))
        status = "completed" if qa_ok else "failed_qa"
        self.db.execute("UPDATE productions SET status=?, current_stage=NULL, updated_at=?, error=? WHERE id=?",
                        (status, now(), None if qa_ok else "quality assurance did not pass", pid))
        self.db.log(pid, f"production {status}")
        return self.get(pid)

    # --- stages ---------------------------------------------------------------------------
    def _stage_intent(self, pid, req, ctx):
        text = req.get("idea") or req.get("script")
        return creative.analyze_intent(text, self.llm() if req.get("idea") else None, req.get("language"),
                                       {k: req[k] for k in ("audience", "message", "product", "platform") if req.get(k)})

    def _stage_concepts(self, pid, req, ctx):
        if req.get("script"):
            return {"skipped": "script supplied by the user", "concepts": [], "chosen": None}
        cs = creative.concepts(ctx["intent"], self._need_llm("concepts"), n=int(req.get("concepts", 3)),
                               duration_s=int(req.get("duration_s", 60)))
        idx = min(int(req.get("concept_index", 0)), len(cs) - 1)
        idea_id = new_id()
        self.db.insert("ideas", {"id": idea_id, "input": ctx["intent"]["idea"], "analysis": ctx["intent"],
                                 "concepts": cs, "created_at": now()})
        return {"concepts": cs, "chosen": idx, "idea_id": idea_id}

    def _stage_script(self, pid, req, ctx):
        intent = ctx["intent"]
        if req.get("script"):
            text, gen = req["script"].strip(), {"source": "user"}
        else:
            concept = ctx["concepts"]["concepts"][ctx["concepts"]["chosen"]]
            gen = scriptgen.generate(intent, concept, float(req.get("duration_s", 60)), self._need_llm("script"),
                                     include_cta=bool(req.get("cta")))
            text = gen["text"]
        sid, vid = new_id(), new_id()
        title = (ctx.get("concepts") or {}).get("concepts", [{}])[ctx.get("concepts", {}).get("chosen") or 0].get("title") \
            if ctx.get("concepts", {}).get("concepts") else (req.get("title") or text[:60])
        self.db.insert("scripts", {"id": sid, "idea_id": ctx.get("concepts", {}).get("idea_id"), "title": title,
                                   "language": intent["language"], "target_s": req.get("duration_s"), "created_at": now()})
        self.db.insert("script_versions", {"id": vid, "script_id": sid, "version": 1, "text": text,
                                           "source": "user" if req.get("script") else "generated", "operation": None,
                                           "mode": None, "est_duration_s": scriptgen.estimate_seconds(text, intent["language"]),
                                           "created_at": now()})
        return gen | {"text": text, "script_id": sid, "version_id": vid, "title": title}

    def _stage_analysis(self, pid, req, ctx):
        s = ctx["script"]
        a = lab.analyze(s["text"], ctx["intent"]["language"], self.llm())
        self.db.execute("UPDATE script_versions SET analysis=? WHERE id=?", (dumps(a), s["version_id"]))
        return a

    def _stage_enhancement(self, pid, req, ctx):
        mode = req.get("enhance_mode")
        s = ctx["script"]
        if not mode:
            return {"skipped": "no enhancement requested", "text": s["text"], "version_id": s["version_id"]}
        r = lab.enhance(s["text"], mode, ctx["intent"]["language"], self.llm())
        if not r["accepted"]:
            self.db.log(pid, f"enhancement rejected: {r['note']}", "warning", "enhancement")
            return r | {"text": s["text"], "version_id": s["version_id"]}
        vid = new_id()
        self.db.insert("script_versions", {"id": vid, "script_id": s["script_id"], "version": 2, "text": r["text"],
                                           "source": "enhanced", "operation": "rewrite", "mode": mode,
                                           "est_duration_s": scriptgen.estimate_seconds(r["text"], ctx["intent"]["language"]),
                                           "created_at": now()})
        return r | {"version_id": vid, "compare": lab.compare(s["text"], r["text"], ctx["intent"]["language"])}

    def _final_text(self, ctx) -> tuple[str, str]:
        e = ctx.get("enhancement") or {}
        return (e.get("text") or ctx["script"]["text"]), (e.get("version_id") or ctx["script"]["version_id"])

    def _stage_emotion(self, pid, req, ctx):
        text, vid = self._final_text(ctx)
        r = emotion.analyze(text, req.get("mode", "natural"), self.llm(), ctx["intent"]["language"])
        for d in r["sentences"]:
            self.db.upsert("emotional_directions", {"script_version_id": vid, "sentence_index": d["index"],
                                                    "data": dumps(d), "edited": 0}, ("script_version_id", "sentence_index"))
        self.db.execute("UPDATE productions SET script_version_id=? WHERE id=?", (vid, pid))
        return r | {"version_id": vid, "directed_script": emotion.to_script(r["sentences"])}

    def _stage_voice(self, pid, req, ctx):
        sel = voice.select(self.settings, self.profiles, ctx["intent"]["language"], req.get("voice"))
        if sel["preset"]:
            name = PRESETS[sel["preset"]]["name"]
            existing = [p for p in self.profiles.list() if p["kind"] == "designed" and p["name"] == name]
            sel["profile_id"] = existing[0]["id"] if existing else self.profiles.create_designed({"preset": sel["preset"]})["id"]
        if req.get("engine"):
            sel["engine"], sel["reason"] = req["engine"], "requested"
        return sel

    def _stage_audio(self, pid, req, ctx):
        # Latest directions from the DB: the user may have edited the timeline before a resume.
        vid = ctx["emotion"]["version_id"]
        dirs = [loads(r["data"]) for r in self.db.all("SELECT data FROM emotional_directions WHERE script_version_id=? "
                                                      "ORDER BY sentence_index", (vid,))]
        v = ctx["voice"]
        from ..tts import engines as _engines
        neural = getattr(_engines(self.settings).get(v["engine"]), "clones_from_reference", False)
        segs, labels = (_neural_phrases(dirs) if neural else _sentence_segments(dirs))
        job = f"prod-{pid}"
        m = generate(self.settings, self.profiles, {
            "segments": segs, "profile_id": v["profile_id"], "engine": v["engine"], "mode": req.get("mode", "natural"),
            "enhance": False, "speed": float(req.get("speed", 1.0)), "pause_scale": float(req.get("pause_scale", 1.0)),
            "pitch": float(req.get("pitch", 0.0)), "soften": float(req.get("soften", 0.0)), "polish": not neural,
            "formats": ["wav", "mp3"], "sample_rate": int(req.get("sample_rate", 48000)),
            "target_lufs": float(req.get("target_lufs", -14.0)), "job_id": job})
        out_dir = self.out_root / pid
        out_dir.mkdir(parents=True, exist_ok=True)
        files = {}
        if req.get("music") or req.get("effects"):
            x, sr = A.load_audio(m["files"]["wav"]["path"])
            mixed, rep = mix.mix(x, sr, req.get("music"), float(req.get("music_db", -18)), float(req.get("duck_db", -10)),
                                 effects=req.get("effects"))
            target = float(req.get("target_lufs", -14.0))
            for _ in range(2):
                mixed = limit(mixed * 10 ** ((target - integrated_loudness(mixed, sr)) / 20), sr, -1.0)
            m["music"] = rep
            for fmt in ("wav", "mp3"):
                files[fmt] = str(A.export(out_dir / f"production.{fmt}", mixed, sr, fmt))
        else:
            for fmt in ("wav", "mp3"):
                files[fmt] = str(shutil.copy(m["files"][fmt]["path"], out_dir / f"production.{fmt}"))
        shutil.copy(self.settings.outputs_dir / job / "manifest.json", out_dir / "render-manifest.json")
        return {"files": files, "duration_s": m["mastering"]["duration_s"], "timeline": m["timeline"],
                "engine": m["engine"], "mastering": {k: v for k, v in m["mastering"].items() if k != "time_map"},
                "music": m.get("music"), "polish": m.get("polish"), "sentences": len(segs), "labels": labels,
                "rendering": "neural phrases: no time-stretch, emotion via intensity and pauses" if neural
                else "one segment per sentence with full prosody",
                "elapsed_s": m["elapsed_s"]}

    def _stage_subtitles(self, pid, req, ctx):
        a = ctx["audio"]
        cue_list = subtitles.cues(a["timeline"])
        problems = subtitles.validate(cue_list, a["duration_s"])
        paths = subtitles.write_all(cue_list, self.out_root / pid)
        for fmt, p in paths.items():
            self.db.upsert("subtitles", {"production_id": pid, "format": fmt, "path": str(p), "cues": len(cue_list)},
                           ("production_id", "format"))
        return {"cues": cue_list, "files": {k: str(v) for k, v in paths.items()}, "problems": problems}

    def _stage_qa(self, pid, req, ctx):
        a, s = ctx["audio"], ctx["subtitles"]
        text, _ = self._final_text(ctx)
        r = qa.check(a["files"], a["duration_s"], float(req.get("target_lufs", -14.0)), s["cues"], a["sentences"],
                     text, asr=_asr() if os.environ.get("NOVA_ASR") == "1" else None)
        if s["problems"]:
            r["checks"].append({"check": "subtitle timing valid", "ok": False, "detail": s["problems"][:5], "required": True})
            r["passed"] = False
        self.db.upsert("quality_reports", {"production_id": pid, "passed": int(r["passed"]), "report": dumps(r),
                                           "created_at": now()}, ("production_id",))
        return r

    def _stage_deliver(self, pid, req, ctx):
        a, q = ctx["audio"], ctx["qa"]
        self.db.execute("DELETE FROM audio_assets WHERE production_id=?", (pid,))
        for fmt, path in a["files"].items():
            info = q["files"].get(fmt, {})
            self.db.insert("audio_assets", {"id": new_id(), "production_id": pid, "format": fmt, "path": path,
                                            "bytes": info.get("bytes"), "duration_s": info.get("duration"),
                                            "sample_rate": info.get("sample_rate"), "sha256": info.get("sha256"),
                                            "created_at": now()})
        labels = dict(enumerate(a.get("labels") or []))  # one label per rendered segment
        for t in a["timeline"]:
            self.db.upsert("audio_segments", {"production_id": pid, "idx": t["index"], "scene": t["scene"],
                                              "text": t["text"], "emotion": labels.get(t["index"]),
                                              "start_s": t["start_s"], "end_s": t["end_s"]}, ("production_id", "idx"))
        return {"delivered": list(a["files"]), "qa_passed": q["passed"], "folder": str(self.out_root / pid)}

    def _need_llm(self, what: str) -> LLMClient:
        llm = self.llm()
        if not llm:
            raise StageError(f"{what} needs the local LLM: set it in Settings (llama.cpp, Ollama, LM Studio)")
        return llm


_ASR = None


def _asr():
    """Whisper-small through transformers, if installed (neural install). Loaded once."""
    global _ASR
    if _ASR is None:
        import subprocess
        from transformers import pipeline
        p = pipeline("automatic-speech-recognition", model="openai/whisper-small", device="cpu")

        def run(path: str) -> str:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                                 capture_output=True, check=True).stdout
            x = np.frombuffer(raw, np.float32)
            parts = [p({"raw": x[i:i + 16000 * 25].copy(), "sampling_rate": 16000},
                       generate_kwargs={"language": "indonesian", "task": "transcribe"})["text"]
                     for i in range(0, x.size, 16000 * 20)]  # 25 s windows, 5 s overlap
            return " ".join(parts)
        _ASR = run
    return _ASR


def _sentence_segments(dirs: list[dict]) -> tuple[list[dict], list[str]]:
    segs = []
    for i, d in enumerate(dirs):
        nxt_before = dirs[i + 1]["pause_before_ms"] if i + 1 < len(dirs) else 0
        segs.append({"text": d["text"], "emotion": d["engine_emotion"], "label": d["emotion"],
                     "prosody": d["prosody"] | {"emphasis": d["emphasis"]},
                     "pause_after_ms": 0 if i + 1 == len(dirs) else d["pause_after_ms"] + nxt_before})
    return segs, [d["emotion"] for d in dirs]


CALM = {"sad", "heartbroken", "nostalgic", "peaceful", "vulnerable", "whispering", "reflective", "comforting",
        "compassionate", "romantic", "suspenseful", "disappointed", "serious", "grateful"}


def _neural_phrases(dirs: list[dict], max_chars: int = 280) -> tuple[list[dict], list[str]]:
    """For a neural cloning engine (Chatterbox): join neighbouring sentences into phrases spoken in
    one breath group, so the melody flows. Speed stays 1.0 (this engine can only change speed by
    time-stretching, which the owner heard as robotic); emotion is carried by intensity
    (exaggeration), loudness and the pauses between phrases. A phrase breaks where the mood turns
    (calm <-> energetic) or intensity jumps by more than 25."""
    groups: list[list[dict]] = []
    for d in dirs:
        g = groups[-1] if groups else None
        if (g and len(" ".join(x["text"] for x in g)) + 1 + len(d["text"]) <= max_chars
                and (g[-1]["emotion"] in CALM) == (d["emotion"] in CALM)
                and abs(g[-1]["intensity"] - d["intensity"]) <= 25):
            g.append(d)
        else:
            groups.append([d])
    segs, labels = [], []
    for i, g in enumerate(groups):
        n = len(g)
        pr = {"rate": 1.0, "pitch_semitones": 0.0,
              "pitch_range": round(sum(x["prosody"]["pitch_range"] for x in g) / n, 3),
              "volume_db": round(sum(x["prosody"]["volume_db"] for x in g) / n, 2)}
        nxt_before = groups[i + 1][0]["pause_before_ms"] if i + 1 < len(groups) else 0
        segs.append({"text": " ".join(x["text"] for x in g), "emotion": g[0]["engine_emotion"], "label": g[0]["emotion"],
                     "prosody": pr, "pause_after_ms": 0 if i + 1 == len(groups) else g[-1]["pause_after_ms"] + nxt_before})
        labels.append(g[0]["emotion"] if n == 1 else f"{g[0]['emotion']} → {g[-1]['emotion']}")
    return segs, labels
