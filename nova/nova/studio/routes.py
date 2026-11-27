"""HTTP API for NOVA Studio (/api/v100/...). OpenAPI docs: /docs."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import Settings
from ..profiles import ProfileStore
from . import creative, emotion, lab, scriptgen, voice
from .db import Store, dumps, loads, new_id, now
from .learning import Learning
from .orchestrator import Orchestrator
from .scheduler import Calendar, Scheduler

PRODUCTION_FILES = {"production.wav", "production.mp3", "subtitles.srt", "subtitles.vtt", "subtitles.json",
                    "subtitles.txt", "render-manifest.json"}


class Studio:
    def __init__(self, settings: Settings, profiles: ProfileStore) -> None:
        self.settings = settings
        self.db = Store(settings.data_dir / "studio.db")
        self.orch = Orchestrator(settings, profiles, self.db)
        self.scheduler = Scheduler(self.db, self._run_scheduled, float(os.environ.get("NOVA_SCHEDULER_POLL", "15")))
        self.calendar = Calendar(self.db)
        self.learning = Learning(self.db)
        self.profiles = profiles
        # A restart leaves productions that were mid-run as "running": mark them resumable.
        self.db.execute("UPDATE productions SET status='interrupted', updated_at=? WHERE status IN ('running','queued')",
                        (now(),))
        self.db.execute("UPDATE production_stages SET status='pending' WHERE status='running'")

    def _run_scheduled(self, payload: dict, run_id: str, key: str) -> dict:
        p = self.orch.create(payload, idempotency_key=key, job_run_id=run_id)
        if p.get("duplicate") and p["status"] in ("completed", "failed_qa", "failed"):
            return p
        return self.orch.run(p["id"])


# --- request models ------------------------------------------------------------------------
class ProductionIn(BaseModel):
    idea: str | None = Field(default=None, max_length=4000)
    script: str | None = Field(default=None, max_length=60000)
    language: Literal["id", "en", "ur", "roman-ur", "ar"] | None = None
    duration_s: float = Field(default=60, ge=10, le=900)
    concepts: int = Field(default=3, ge=1, le=6)
    concept_index: int = Field(default=0, ge=0, le=5)
    enhance_mode: str | None = None
    mode: Literal["natural", "professional", "expressive"] = "natural"
    voice: str | None = None
    engine: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pause_scale: float = Field(default=1.0, ge=0.0, le=3.0)
    pitch: float = Field(default=0.0, ge=-6, le=6)
    soften: float = Field(default=0.0, ge=0, le=1)
    target_lufs: float = Field(default=-14.0, ge=-30, le=-8)
    music: str | None = None
    music_db: float = Field(default=-18, ge=-40, le=-6)
    cta: bool = False
    audience: str | None = Field(default=None, max_length=500)
    message: str | None = Field(default=None, max_length=500)
    platform: str | None = Field(default=None, max_length=40)


class IdeaIn(BaseModel):
    idea: str = Field(min_length=3, max_length=4000)
    language: str | None = None
    n: int = Field(default=3, ge=1, le=6)
    duration_s: int = Field(default=60, ge=10, le=900)


class ScriptGenIn(BaseModel):
    idea: str = Field(min_length=3, max_length=4000)
    language: str | None = None
    duration_s: float = Field(default=60, ge=10, le=900)
    concept: dict | None = None


class LabIn(BaseModel):
    text: str = Field(min_length=1, max_length=60000)
    language: str = "id"


class VersionIn(BaseModel):
    mode: str = "natural"
    operation: str = "rewrite"
    sentence_index: int | None = None
    text: str | None = Field(default=None, max_length=60000)  # a manual edit by the user


class EmotionIn(BaseModel):
    text: str = Field(min_length=1, max_length=60000)
    mode: Literal["natural", "professional", "expressive"] = "natural"
    language: str = "id"


class EmotionEditIn(BaseModel):
    emotion: str | None = None
    intensity: int | None = Field(default=None, ge=10, le=100)
    pause_before_ms: int | None = Field(default=None, ge=0, le=5000)
    pause_after_ms: int | None = Field(default=None, ge=0, le=5000)
    emphasis: list[str] | None = None


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    production: ProductionIn
    schedule: dict
    timezone: str = "UTC"
    priority: int = Field(default=5, ge=1, le=9)
    max_retries: int = Field(default=1, ge=0, le=5)
    depends_on: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)


class CalendarIn(BaseModel):
    date: str
    title: str = Field(min_length=1, max_length=200)
    timezone: str = "UTC"
    time: str | None = None
    platform: str | None = None
    category: str | None = None
    theme: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


class CalendarPatch(BaseModel):
    status: str | None = None
    title: str | None = None
    time: str | None = None
    platform: str | None = None
    notes: str | None = None


class RecurringIn(BaseModel):
    theme: str
    title_template: str = Field(max_length=200)
    start: str
    weeks: int = Field(default=4, ge=1, le=26)
    weekdays: list[int]
    timezone: str = "UTC"
    time: str | None = None
    platform: str | None = None
    category: str | None = None


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class MetricIn(BaseModel):
    production_id: str | None = None
    platform: str
    metric: str
    value: float


def register(app: FastAPI, settings: Settings, profiles: ProfileStore, deps: list) -> Studio:
    studio = Studio(settings, profiles)
    app.state.studio = studio
    hits: dict[str, deque] = defaultdict(deque)
    limit_per_min = int(os.environ.get("NOVA_RATE_LIMIT", "60"))
    lock = threading.Lock()

    def rate_limit(request: Request):
        if request.method == "GET":
            return
        key = request.client.host if request.client else "local"
        t = time.time()
        with lock:
            q = hits[key]
            while q and t - q[0] > 60:
                q.popleft()
            if len(q) >= limit_per_min:
                raise HTTPException(429, "too many requests: try again in a minute")
            q.append(t)

    d = deps + [Depends(rate_limit)]
    o, llm = studio.orch, studio.orch.llm

    @app.on_event("startup")
    def _start_scheduler():
        if os.environ.get("NOVA_SCHEDULER", "1") != "0":
            studio.scheduler.start()

    @app.on_event("shutdown")
    def _stop_scheduler():
        studio.scheduler.stop()

    # productions -------------------------------------------------------------------------------
    @app.post("/api/v100/productions", dependencies=d)
    def create_production(body: ProductionIn):
        if not (body.idea or body.script):
            raise HTTPException(422, "idea or script required")
        if body.enhance_mode and body.enhance_mode not in lab.MODES:
            raise HTTPException(422, f"enhance_mode must be one of {sorted(lab.MODES)}")
        _check_music(body.music)
        p = o.create(body.model_dump(exclude_none=True))
        o.submit(p["id"])
        return p

    def _check_music(path):
        if path and not (Path(path).resolve().is_relative_to(settings.data_dir.resolve()) and Path(path).is_file()):
            raise HTTPException(422, "music must be a file you uploaded into the NOVA data folder")

    @app.get("/api/v100/productions", dependencies=deps)
    def list_productions(limit: int = 50):
        return o.list(limit)

    @app.get("/api/v100/productions/{pid}", dependencies=deps)
    def get_production(pid: str):
        try:
            return o.get(pid)
        except KeyError:
            raise HTTPException(404, "production not found")

    @app.get("/api/v100/productions/{pid}/logs", dependencies=deps)
    def production_logs(pid: str):
        return o.logs(pid)

    @app.post("/api/v100/productions/{pid}/resume", dependencies=d)
    def resume_production(pid: str):
        try:
            p = o.resume(pid)
        except KeyError:
            raise HTTPException(404, "production not found")
        o.submit(pid)
        return p

    @app.post("/api/v100/productions/{pid}/redo/{stage}", dependencies=d)
    def redo_stage(pid: str, stage: str):
        """Re-run one stage and everything after it (e.g. 'audio' after editing emotions)."""
        from .orchestrator import STAGES
        if stage not in STAGES:
            raise HTTPException(422, f"stage must be one of {STAGES}")
        later = STAGES[STAGES.index(stage):]
        for st in later:
            studio.db.execute("UPDATE production_stages SET status='pending', output=NULL WHERE production_id=? AND stage=?",
                              (pid, st))
        studio.db.execute("UPDATE productions SET status='queued', updated_at=? WHERE id=?", (now(), pid))
        o.submit(pid)
        return o.get(pid)

    @app.get("/api/v100/productions/{pid}/files/{name}", dependencies=deps)
    def production_file(pid: str, name: str):
        if name not in PRODUCTION_FILES or not pid.isalnum():
            raise HTTPException(404, "not found")
        path = o.out_root / pid / name
        if not path.is_file():
            raise HTTPException(404, "not found")
        media = {"wav": "audio/wav", "mp3": "audio/mpeg", "srt": "application/x-subrip", "vtt": "text/vtt",
                 "json": "application/json", "txt": "text/plain"}[name.rsplit(".", 1)[1]]
        return FileResponse(path, media_type=media, filename=f"nova-{pid[:8]}-{name}")

    @app.post("/api/v100/productions/{pid}/feedback", dependencies=d)
    def production_feedback(pid: str, body: FeedbackIn):
        try:
            return studio.learning.feedback(pid, body.rating, body.comment)
        except KeyError:
            raise HTTPException(404, "production not found")

    # engines -----------------------------------------------------------------------------------
    @app.post("/api/v100/creative/analyze", dependencies=d)
    def creative_analyze(body: IdeaIn):
        return creative.analyze_intent(body.idea, llm(), body.language)

    @app.post("/api/v100/creative/concepts", dependencies=d)
    def creative_concepts(body: IdeaIn):
        intent = creative.analyze_intent(body.idea, llm(), body.language)
        try:
            return {"intent": intent, "concepts": creative.concepts(intent, llm(), body.n, body.duration_s)}
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))

    @app.post("/api/v100/scripts/generate", dependencies=d)
    def script_generate(body: ScriptGenIn):
        intent = creative.analyze_intent(body.idea, llm(), body.language)
        try:
            gen = scriptgen.generate(intent, body.concept, body.duration_s, llm())
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        sid, vid = new_id(), new_id()
        studio.db.insert("scripts", {"id": sid, "title": body.idea[:80], "language": intent["language"],
                                     "target_s": body.duration_s, "created_at": now()})
        studio.db.insert("script_versions", {"id": vid, "script_id": sid, "version": 1, "text": gen["text"],
                                             "source": "generated", "est_duration_s": gen["estimated_s"], "created_at": now()})
        return gen | {"script_id": sid, "version_id": vid}

    @app.get("/api/v100/scripts", dependencies=deps)
    def list_scripts():
        return studio.db.all("SELECT s.*, (SELECT MAX(version) FROM script_versions v WHERE v.script_id=s.id) AS versions "
                             "FROM scripts s ORDER BY created_at DESC LIMIT 100")

    @app.get("/api/v100/scripts/{sid}", dependencies=deps)
    def get_script(sid: str):
        s = studio.db.one("SELECT * FROM scripts WHERE id=?", (sid,))
        if not s:
            raise HTTPException(404, "script not found")
        s["versions"] = studio.db.all("SELECT id, version, text, source, operation, mode, est_duration_s, created_at "
                                      "FROM script_versions WHERE script_id=? ORDER BY version", (sid,))
        return s

    @app.post("/api/v100/scripts/{sid}/versions", dependencies=d)
    def new_version(sid: str, body: VersionIn):
        latest = studio.db.one("SELECT * FROM script_versions WHERE script_id=? ORDER BY version DESC LIMIT 1", (sid,))
        if not latest:
            raise HTTPException(404, "script not found")
        lang = (studio.db.one("SELECT language FROM scripts WHERE id=?", (sid,)) or {}).get("language") or "id"
        if body.text:
            r = {"text": body.text.strip(), "accepted": True, "method": "user"}
            op, src = "manual", "user"
        else:
            try:
                r = lab.enhance(latest["text"], body.mode, lang, llm(), body.operation, body.sentence_index)
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(422, str(exc))
            op, src = body.operation, "enhanced"
            if not r["accepted"]:
                return r | {"saved": False}
        vid = new_id()
        studio.db.insert("script_versions", {"id": vid, "script_id": sid, "version": latest["version"] + 1,
                                             "text": r["text"], "source": src, "operation": op, "mode": body.mode,
                                             "est_duration_s": scriptgen.estimate_seconds(r["text"], lang), "created_at": now()})
        return r | {"saved": True, "version_id": vid, "version": latest["version"] + 1,
                    "compare": lab.compare(latest["text"], r["text"], lang)}

    @app.get("/api/v100/scripts/{sid}/compare", dependencies=deps)
    def compare_versions(sid: str, a: int, b: int):
        va = studio.db.one("SELECT text FROM script_versions WHERE script_id=? AND version=?", (sid, a))
        vb = studio.db.one("SELECT text FROM script_versions WHERE script_id=? AND version=?", (sid, b))
        if not (va and vb):
            raise HTTPException(404, "version not found")
        return lab.compare(va["text"], vb["text"])

    @app.post("/api/v100/lab/analyze", dependencies=d)
    def lab_analyze(body: LabIn):
        return lab.analyze(body.text, body.language, llm())

    @app.post("/api/v100/emotion/analyze", dependencies=d)
    def emotion_analyze(body: EmotionIn):
        r = emotion.analyze(body.text, body.mode, llm(), body.language)
        return r | {"directed_script": emotion.to_script(r["sentences"])}

    @app.get("/api/v100/emotion/library", dependencies=deps)
    def emotion_library():
        return [{"emotion": k, "engine_emotion": v[0], "delivery": v[1], "speed": v[2], "pitch": v[3]}
                for k, v in emotion.LIBRARY.items()]

    @app.get("/api/v100/emotion/{version_id}", dependencies=deps)
    def emotion_timeline(version_id: str):
        rows = studio.db.all("SELECT data, edited FROM emotional_directions WHERE script_version_id=? ORDER BY sentence_index",
                             (version_id,))
        if not rows:
            raise HTTPException(404, "no directions for this script version")
        return [loads(r["data"]) | {"edited": bool(r["edited"])} for r in rows]

    @app.put("/api/v100/emotion/{version_id}/{index}", dependencies=d)
    def emotion_edit(version_id: str, index: int, body: EmotionEditIn):
        rows = studio.db.all("SELECT data FROM emotional_directions WHERE script_version_id=? ORDER BY sentence_index",
                             (version_id,))
        if not 0 <= index < len(rows):
            raise HTTPException(404, "sentence not found")
        try:
            new = emotion.edit([loads(r["data"]) for r in rows], index, body.emotion, body.intensity,
                               **body.model_dump(exclude={"emotion", "intensity"}))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        for i, dd in enumerate(new):
            studio.db.execute("UPDATE emotional_directions SET data=?, edited=CASE WHEN ?=1 THEN 1 ELSE edited END "
                              "WHERE script_version_id=? AND sentence_index=?", (dumps(dd), int(i == index), version_id, i))
        return new

    @app.get("/api/v100/voice/adapters", dependencies=deps)
    def voice_adapters():
        return voice.adapters(settings)

    @app.get("/api/v100/voice/catalog", dependencies=deps)
    def voice_catalog():
        return voice.catalog(settings, profiles)

    # scheduling ---------------------------------------------------------------------------------
    @app.post("/api/v100/schedule/jobs", dependencies=d)
    def create_job(body: JobIn):
        try:
            return studio.scheduler.create(body.name, body.production.model_dump(exclude_none=True), body.schedule,
                                           body.timezone, body.priority, body.max_retries, body.depends_on,
                                           body.idempotency_key)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, f"invalid schedule: {exc}")

    @app.get("/api/v100/schedule/jobs", dependencies=deps)
    def list_jobs():
        return studio.scheduler.list()

    @app.post("/api/v100/schedule/jobs/{job_id}/enable", dependencies=d)
    def enable_job(job_id: str, enabled: bool = True):
        j = studio.scheduler.set_enabled(job_id, enabled)
        if not j:
            raise HTTPException(404, "job not found")
        return j

    @app.delete("/api/v100/schedule/jobs/{job_id}", dependencies=d)
    def delete_job(job_id: str):
        studio.scheduler.delete(job_id)
        return {"deleted": job_id}

    @app.get("/api/v100/schedule/runs", dependencies=deps)
    def list_runs(job_id: str | None = None):
        return studio.scheduler.runs(job_id)

    @app.post("/api/v100/schedule/tick", dependencies=d)
    def tick_now():
        """Run every due job now (normally the background scheduler does this)."""
        return studio.scheduler.tick()

    @app.get("/api/v100/calendar", dependencies=deps)
    def calendar_list(start: str | None = None, end: str | None = None):
        return studio.calendar.list(start, end)

    @app.post("/api/v100/calendar", dependencies=d)
    def calendar_add(body: CalendarIn):
        try:
            return studio.calendar.add(body.date, body.title, body.timezone, body.time, body.platform, body.category,
                                       body.theme, body.notes)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc))

    @app.post("/api/v100/calendar/recurring", dependencies=d)
    def calendar_recurring(body: RecurringIn):
        try:
            return studio.calendar.recurring(body.theme, body.title_template, body.start, body.weeks, body.weekdays,
                                             body.timezone, body.time, body.platform, body.category)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc))

    @app.patch("/api/v100/calendar/{entry_id}", dependencies=d)
    def calendar_patch(entry_id: str, body: CalendarPatch):
        try:
            r = studio.calendar.update(entry_id, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not r:
            raise HTTPException(404, "entry not found")
        return r

    @app.get("/api/v100/calendar/times/{platform}", dependencies=deps)
    def calendar_times(platform: str):
        return studio.calendar.recommend_times(platform)

    # learning and system -------------------------------------------------------------------------
    @app.get("/api/v100/learning", dependencies=deps)
    def learning_report():
        return studio.learning.report()

    @app.get("/api/v100/learning/preferences", dependencies=deps)
    def learning_prefs():
        return studio.learning.preferences()

    @app.post("/api/v100/learning/reset", dependencies=d)
    def learning_reset():
        return studio.learning.reset()

    @app.post("/api/v100/metrics", dependencies=d)
    def add_metric(body: MetricIn):
        return studio.learning.metric(body.production_id, body.platform, body.metric, body.value)

    @app.get("/api/v100/notifications", dependencies=deps)
    def notifications(unread: bool = False):
        q = "SELECT * FROM notifications" + (" WHERE read=0" if unread else "") + " ORDER BY id DESC LIMIT 100"
        return studio.db.all(q)

    @app.get("/api/v100/status", dependencies=deps)
    def studio_status():
        return {"schema_version": studio.db.schema_version(), "llm": bool(settings.llm_base_url),
                "scheduler_running": bool(studio.scheduler._thread and studio.scheduler._thread.is_alive()),
                "jobs": len(studio.scheduler.list()), "productions": len(o.list(1000)),
                "engines": [{"name": a["name"], "status": a["status"]} for a in voice.adapters(settings)]}

    return studio
