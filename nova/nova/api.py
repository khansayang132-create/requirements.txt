"""HTTP API + static studio UI. Run: uvicorn nova.api:app --host 127.0.0.1 --port 8000"""
from __future__ import annotations

import hmac
import json
import re
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .analysis import analyze_voice
from .audio import AudioError, load_audio
from .config import Settings
from .director import direct, render_script
from .enhance import MODES, enhance
from .llm import LLMClient
from .pipeline import VALID_EMOTIONS, generate, master_upload, preview_profile
from .profiles import PRESETS, ConsentError, ProfileNotFound, ProfileStore
from .lskhan import PlanError
from .lskhan import fill as lskhan_fill
from .lskhan import parse as lskhan_parse
from .lskhan import segments as lskhan_segments
from .lskhan import timing_report
from .runtime import Runtime, explain_error, install_piper_voice, list_models, test_llm
from .script_judge import judge
from .tts import TTSUnavailable, engines

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ID_RE = re.compile(r"^[a-zA-Z0-9-]{1,80}$")


class Segment(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    emotion: str | None = None
    label: str | None = None


class ScriptIn(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


class EnhanceIn(ScriptIn):
    mode: Literal["natural", "professional", "expressive"] = "natural"


class DirectIn(EnhanceIn):
    emotion: str | None = None


class DesignIn(BaseModel):
    preset: str | None = None
    name: str | None = None
    language: str | None = None
    pitch_hz: float | None = None
    range_semitones: float | None = None
    formant_scale_hz: float | None = None
    breathiness: float | None = None
    rate: float | None = None
    volume_db: float | None = None
    variant: Literal["m3", "f3"] | None = None


class GenerateIn(BaseModel):
    text: str | None = Field(default=None, max_length=50000)
    segments: list[Segment] | None = None
    profile_id: str | None = None
    engine: str | None = None
    voice: str | None = None
    mode: Literal["natural", "professional", "expressive"] = "natural"
    enhance: bool = True
    emotion: str | None = None
    speed: float = 1.0
    pitch: float = 0.0
    volume_db: float = 0.0
    pause_scale: float = 1.0
    pronunciation: dict[str, str] = {}
    formats: list[Literal["wav", "mp3"]] = ["wav", "mp3"]
    sample_rate: int = 48000
    target_lufs: float = -16.0
    project_id: str | None = None


class LLMSettingsIn(BaseModel):
    provider: str
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    clear_key: bool = False
    thinking: bool = False


class LskhanIn(BaseModel):
    source: str | dict = Field(...)


class LskhanRenderIn(BaseModel):
    source: str | dict
    answers: dict[str, str] = {}
    profile_id: str | None = None
    engine: str | None = None
    mode: Literal["natural", "professional", "expressive"] = "expressive"
    enhance: bool = True
    speed: float = 1.0
    pitch: float = 0.0
    volume_db: float = 0.0
    pause_scale: float = 1.0
    pronunciation: dict[str, str] = {}
    formats: list[Literal["wav", "mp3"]] = ["wav", "mp3"]
    sample_rate: int = 48000
    target_lufs: float = -14.0


class ModelsIn(BaseModel):
    base_url: str = Field(max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class ToggleIn(BaseModel):
    enabled: bool


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    data: dict = {}


class Jobs:
    def __init__(self) -> None:
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.items: dict[str, dict] = {}
        self.lock = threading.Lock()

    def submit(self, fn, req: dict) -> dict:
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "status": "queued", "progress": 0, "message": "queued",
               "created_at": datetime.now(timezone.utc).isoformat(), "result": None, "error": None}
        with self.lock:
            self.items[job_id] = job

        def progress(p: int, msg: str) -> None:
            job.update(progress=p, message=msg)

        def run() -> None:
            job["status"] = "running"
            try:
                job["result"] = fn(req | {"job_id": job_id}, progress)
                job["status"] = "done"
            except Exception as exc:  # recorded and shown; the worker keeps running
                job.update(status="failed", error=f"{type(exc).__name__}: {exc}")

        self.pool.submit(run)
        return job


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    store = ProfileStore(settings)
    runtime = Runtime(settings, store.fernet)  # saved app settings override environment defaults
    jobs = Jobs()
    app = FastAPI(title="NOVA OMNIVERSE", version=__version__)

    def auth(request: Request) -> None:
        if not settings.api_key:
            return
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
        if not hmac.compare_digest(token.encode(), settings.api_key.encode()):
            raise HTTPException(401, "missing or wrong API key")

    @app.exception_handler(ProfileNotFound)
    async def _nf(_, exc):
        return JSONResponse({"detail": f"profile not found: {exc}"}, status_code=404)

    @app.exception_handler(ConsentError)
    async def _consent(_, exc):
        return JSONResponse({"detail": f"consent required: {exc}"}, status_code=403)

    @app.exception_handler(TTSUnavailable)
    async def _tts(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(PlanError)
    async def _plan(_, exc):
        missing = exc.args[1] if len(exc.args) > 1 else []
        return JSONResponse({"detail": str(exc.args[0]), "missing": missing}, status_code=422)

    @app.exception_handler(ValueError)
    async def _val(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    deps = [Depends(auth)]

    @app.get("/api/system", dependencies=deps)
    def system():
        return {
            "engines": [e.info() for e in engines(settings).values()],
            "llm": {"configured": bool(settings.llm_base_url), "model": settings.llm_model if settings.llm_base_url else None,
                    "endpoint": settings.llm_base_url or None},
            "modes": list(MODES), "emotions": sorted(VALID_EMOTIONS),
            "presets": [{"id": k, **{f: v[f] for f in ("name", "language", "description")}} for k, v in PRESETS.items()],
            "auth_required": bool(settings.api_key),
        }

    # ---- App settings (AI server, voices) --------------------------------------------------
    @app.get("/api/settings", dependencies=deps)
    def get_settings():
        return runtime.public()

    @app.put("/api/settings/llm", dependencies=deps)
    def save_llm(body: LLMSettingsIn):
        return runtime.update_llm(body.provider, body.base_url, body.model, body.api_key,
                                  body.thinking, body.clear_key)

    @app.post("/api/settings/llm/test", dependencies=deps)
    def llm_test():
        try:
            return {"ok": True} | test_llm(settings)
        except Exception as exc:  # every failure becomes a readable message, not a 500
            return {"ok": False, "error": explain_error(exc), "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}

    @app.post("/api/settings/llm/models", dependencies=deps)
    def llm_models(body: ModelsIn):
        key = body.api_key or (settings.llm_api_key if settings.llm_api_key != "none" else "")
        try:
            return {"ok": True, "models": list_models(body.base_url, key)}
        except Exception as exc:
            return {"ok": False, "models": [], "error": explain_error(exc)}

    @app.post("/api/voices/piper/install", dependencies=deps)
    def piper_install():
        job = jobs.submit(lambda r, p: install_piper_voice(settings, p), {})
        return {"job_id": job["id"]}

    @app.put("/api/settings/chatterbox", dependencies=deps)
    def chatterbox_toggle(body: ToggleIn):
        if body.enabled and not runtime.public()["chatterbox"]["installed"]:
            raise HTTPException(409, "Chatterbox is not installed on this computer: run "
                                     "pip install -r requirements-neural.txt, then restart NOVA")
        runtime.set_chatterbox(body.enabled)
        return runtime.public()

    @app.post("/api/voices/chatterbox/warmup", dependencies=deps)
    def chatterbox_warmup():
        engine = engines(settings)["chatterbox-id"]
        if not engine.available():
            raise HTTPException(409, "enable Chatterbox first")

        def run(_req, progress):
            progress(10, "loading the neural model (the first time downloads about 3 GB)")
            engine._load()
            progress(100, "model loaded and ready")
            return {"loaded": True}
        return {"job_id": jobs.submit(run, {})["id"]}

    # ---- Voice profiles -------------------------------------------------------------------
    @app.post("/api/profiles", dependencies=deps)
    async def create_profile(
        audio: UploadFile = File(...), name: str = Form(""), speaker_name: str = Form(...),
        consent_statement: str = Form(...), relationship: str = Form(...), consent_confirmed: bool = Form(False),
        language: str = Form(""), accent: str = Form(""),
    ):
        consent = {"speaker_name": speaker_name, "statement": consent_statement,
                   "relationship": relationship, "confirmed": consent_confirmed}
        from .profiles import validate_consent
        validate_consent(consent)  # refuse before reading audio
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ("upload" + Path(audio.filename or "a.wav").suffix[:8])
            size = 0
            with path.open("wb") as fh:
                while chunk := await audio.read(1 << 20):
                    size += len(chunk)
                    if size > settings.max_upload_mb << 20:
                        raise HTTPException(413, f"file larger than {settings.max_upload_mb} MB")
                    fh.write(chunk)
            try:
                x, sr = load_audio(path, sr=24000)
            except AudioError as exc:
                raise HTTPException(422, str(exc)) from exc
        x = x[: 24000 * 600]  # analyse at most 10 minutes
        analysis = analyze_voice(x, sr, language, accent)
        profile = store.create(name, x, sr, consent, analysis, language, accent)
        return profile

    @app.post("/api/profiles/design", dependencies=deps)
    def design_profile(body: DesignIn):
        return store.create_designed(body.model_dump(exclude_none=True))

    @app.get("/api/profiles", dependencies=deps)
    def list_profiles():
        return store.list()

    @app.get("/api/profiles/{profile_id}", dependencies=deps)
    def get_profile(profile_id: str):
        return store.get(profile_id)

    @app.delete("/api/profiles/{profile_id}", dependencies=deps)
    def delete_profile(profile_id: str):
        store.delete(profile_id)
        shutil.rmtree(settings.outputs_dir / f"preview-{profile_id}", ignore_errors=True)
        return {"deleted": profile_id}

    @app.post("/api/profiles/{profile_id}/preview", dependencies=deps)
    def preview(profile_id: str, body: dict | None = None):
        path = preview_profile(settings, store, profile_id, (body or {}).get("text"))
        return {"url": f"/api/files/preview-{profile_id}/{path.name}"}

    # ---- Script intelligence ---------------------------------------------------------------
    @app.post("/api/script/analyze", dependencies=deps)
    def analyze(body: ScriptIn):
        return judge(body.text, LLMClient.from_settings(settings))

    @app.post("/api/script/enhance", dependencies=deps)
    def enhance_script(body: EnhanceIn):
        result = enhance(body.text, body.mode, LLMClient.from_settings(settings))
        result["original_score"] = judge(body.text)["score"]
        result["enhanced_score"] = judge(result["enhanced"])["score"]
        return result

    @app.post("/api/script/direct", dependencies=deps)
    def direct_script(body: DirectIn):
        emotion = body.emotion if body.emotion in VALID_EMOTIONS else None
        dirs = direct(body.text, body.mode, emotion)
        return {"directions": [d.to_dict() for d in dirs], "script": render_script(dirs)}

    # ---- Generation ------------------------------------------------------------------------
    @app.post("/api/generate", dependencies=deps)
    def start_generation(body: GenerateIn):
        req = body.model_dump()
        if not req.get("segments") and not req.get("text"):
            raise HTTPException(422, "text or segments required")
        req["segments"] = req.get("segments") or None
        if req.get("profile_id"):
            store.get(req["profile_id"])
        job = jobs.submit(lambda r, p: generate(settings, store, r, p), req)
        return {"job_id": job["id"], "status": job["status"]}

    @app.post("/api/master", dependencies=deps)
    async def master_voiceover(audio: UploadFile = File(...), target_lufs: float = Form(-14.0),
                               sample_rate: int = Form(48000), formats: str = Form("wav,mp3")):
        """Polish an existing voiceover: loudness, peaks, edges, fades. The voice is not changed."""
        if not -30 <= target_lufs <= -8:
            raise HTTPException(422, "target_lufs must be between -30 and -8")
        settings.outputs_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(dir=settings.outputs_dir, prefix="upload-"))
        src = tmp_dir / ("source" + Path(audio.filename or "a.wav").suffix[:8])
        size = 0
        with src.open("wb") as fh:
            while chunk := await audio.read(1 << 20):
                size += len(chunk)
                if size > settings.max_upload_mb << 20:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    raise HTTPException(413, f"file larger than {settings.max_upload_mb} MB")
                fh.write(chunk)
        req = {"target_lufs": target_lufs, "sample_rate": sample_rate,
               "formats": [f for f in formats.split(",") if f], "filename": (audio.filename or "")[:120]}

        def run(r, progress):
            try:
                return master_upload(settings, src, r, progress)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)  # the upload is not kept
        return {"job_id": jobs.submit(run, req)["id"]}

    # ---- LSKhan Studio autopilot bridge ----------------------------------------------------
    @app.post("/api/lskhan/parse", dependencies=deps)
    def lskhan_parse_route(body: LskhanIn):
        return lskhan_parse(body.source)

    @app.post("/api/lskhan/render", dependencies=deps)
    def lskhan_render(body: LskhanRenderIn):
        plan = lskhan_parse(body.source)
        segs = lskhan_segments(plan, lskhan_fill(plan, body.answers))  # refuses unanswered placeholders
        if body.profile_id:
            store.get(body.profile_id)
        req = body.model_dump(exclude={"source", "answers"}) | {"segments": segs}

        def run(r, progress):
            manifest = generate(settings, store, r, progress)
            manifest["lskhan"] = {"title": plan["title"], "type": plan["type"], "timing": timing_report(manifest, segs)}
            (settings.outputs_dir / manifest["id"] / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            return manifest
        return {"job_id": jobs.submit(run, req)["id"], "segments": segs}

    @app.get("/api/jobs/{job_id}", dependencies=deps)
    def job_status(job_id: str):
        job = jobs.items.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        out = dict(job)
        if job["result"] and "files" in job["result"]:  # voice jobs return no audio files
            out["result"] = dict(job["result"]) | {"urls": {
                fmt: f"/api/files/{job_id}/voiceover.{fmt}" for fmt in job["result"]["files"]}}
        return out

    @app.get("/api/files/{job_id}/{filename}", dependencies=deps)
    def download(job_id: str, filename: str):
        if not ID_RE.match(job_id) or filename not in ("voiceover.wav", "voiceover.mp3", "manifest.json"):
            raise HTTPException(404, "not found")
        path = settings.outputs_dir / job_id / filename
        if not path.is_file():
            raise HTTPException(404, "not found")
        media = {"wav": "audio/wav", "mp3": "audio/mpeg", "json": "application/json"}[filename.rsplit(".", 1)[1]]
        return FileResponse(path, media_type=media, filename=f"nova-{job_id[:8]}-{filename}")

    # ---- Projects --------------------------------------------------------------------------
    def _project_path(pid: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", pid):
            raise HTTPException(404, "project not found")
        return settings.projects_dir / f"{pid}.json"

    @app.get("/api/projects", dependencies=deps)
    def list_projects():
        items = []
        for f in sorted(settings.projects_dir.glob("*.json")):
            p = json.loads(f.read_text())
            items.append({k: p[k] for k in ("id", "name", "updated_at")})
        return sorted(items, key=lambda p: p["updated_at"], reverse=True)

    @app.post("/api/projects", dependencies=deps)
    def save_project(body: ProjectIn, project_id: str | None = None):
        pid = project_id or uuid.uuid4().hex
        path = _project_path(pid)
        now = datetime.now(timezone.utc).isoformat()
        created = json.loads(path.read_text())["created_at"] if path.exists() else now
        project = {"id": pid, "name": body.name, "data": body.data, "created_at": created, "updated_at": now}
        path.write_text(json.dumps(project, ensure_ascii=False))
        return project

    @app.get("/api/projects/{project_id}", dependencies=deps)
    def get_project(project_id: str):
        path = _project_path(project_id)
        if not path.exists():
            raise HTTPException(404, "project not found")
        return json.loads(path.read_text())

    @app.delete("/api/projects/{project_id}", dependencies=deps)
    def delete_project(project_id: str):
        path = _project_path(project_id)
        if not path.exists():
            raise HTTPException(404, "project not found")
        path.unlink()
        return {"deleted": project_id}

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
