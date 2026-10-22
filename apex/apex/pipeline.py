"""End-to-end production: script -> lock -> TTS -> storyboard -> 3D render -> edit -> QA -> manifest."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__
from .assemble import assemble
from .media import probe_duration
from .models import ProductionSpec, Script, Storyboard
from .qa import technical_qa
from .script_engine import lock_script, provider_from_env, review_script, write_script
from .storyboard import build_storyboard
from .subtitles import build_srt, build_title_srt, validate_srt
from .timing import fits_target
from .tts import EspeakProvider


class PipelineError(RuntimeError):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class RenderSettings:
    fps: int = 24
    samples: int = 8
    blender_python: str = field(default_factory=lambda: sys.executable)
    scene_timeout_seconds: int = 3 * 3600


def _sha(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


RENDERER_SOURCE = Path(__file__).with_name("render3d.py")


def render_scene(scene: dict, board: Storyboard, settings: RenderSettings, renders: Path,
                 log: Callable[[str], None]) -> tuple[Path, dict, bool]:
    """Render one scene unless an identical render already exists. Returns (dir, info, reused)."""
    key = _sha(scene["template"], scene["camera_move"], scene["params"], scene["duration"], board.fps,
               board.width, board.height, settings.samples, __version__, _file_sha(RENDERER_SOURCE))
    out = renders / f"{scene['scene_id']}_{key}"
    frames = max(1, round(scene["duration"] * board.fps))
    info_file = out / "render_info.json"
    if info_file.exists() and len(list(out.glob("frame_*.png"))) == frames:
        return out, json.loads(info_file.read_text()), True
    renders.mkdir(parents=True, exist_ok=True)
    spec_file = renders / f"{scene['scene_id']}_{key}.json"
    spec_file.write_text(json.dumps(scene))
    log(f"render {scene['scene_id']} ({scene['template']}, {frames} frames)")
    proc = subprocess.run([settings.blender_python, "-m", "apex.render3d", str(spec_file), str(out),
                           "--fps", str(board.fps), "--width", str(board.width), "--height", str(board.height),
                           "--samples", str(settings.samples)],
                          cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True,
                          timeout=settings.scene_timeout_seconds)
    if proc.returncode != 0 or not info_file.exists():
        raise PipelineError(f"render failed for {scene['scene_id']}: {(proc.stderr or proc.stdout)[-1200:]}",
                            retryable=True)
    got = len(list(out.glob("frame_*.png")))
    if got != frames:
        raise PipelineError(f"{scene['scene_id']}: expected {frames} frames, renderer wrote {got}", retryable=True)
    return out, json.loads(info_file.read_text()), False


def run_production(spec: ProductionSpec, project: Path, script_file: Path | None = None,
                   settings: RenderSettings | None = None, log: Callable[[str], None] = print,
                   heartbeat: Callable[[], None] = lambda: None) -> dict:
    settings = settings or RenderSettings()
    project.mkdir(parents=True, exist_ok=True)
    started = time.time()
    stages: list[dict] = []

    def stage(name: str, status: str, detail: str = "") -> None:
        stages.append({"stage": name, "status": status, "detail": detail, "at": round(time.time() - started, 1)})
        log(f"[{name}] {status} {detail}")
        heartbeat()

    # 1. Script: from an approved file, or written by an LLM provider with bounded self-review.
    if script_file:
        script = Script.model_validate_json(Path(script_file).read_text(encoding="utf-8"))
        review_log = [{"attempt": 1, "version": script.version_hash, "problems": review_script(script, spec)}]
    else:
        script, review_log = write_script(spec, provider_from_env())
    if review_log[-1]["problems"]:
        raise PipelineError("script failed review: " + "; ".join(review_log[-1]["problems"]), retryable=False)
    lock = lock_script(script, project)
    stage("script", "LOCKED", f"version {lock['version']} ({script.provenance})")

    # 2. Narration audio, one clip per scene, cached by text + voice.
    tts = EspeakProvider()
    wavs, spoken = [], []
    for sc in script.scenes:
        wav = project / "audio" / f"{sc.scene_id}_{_sha(sc.narration, tts.name, spec.language)}.wav"
        if not wav.exists():
            tts.synthesize(sc.narration, spec.language, wav)
        wavs.append(wav)
        spoken.append(probe_duration(wav))
    stage("narration", "DONE", f"{len(wavs)} clips, {sum(spoken):.1f}s spoken ({tts.name})")

    # 3. Storyboard from measured narration; must land inside the target length.
    board = build_storyboard(script, spoken, spec.aspect_ratio, settings.fps)
    (project / "storyboard.json").write_text(board.model_dump_json(indent=2))
    if not fits_target(board.total_seconds, spec.target_seconds, spec.tolerance_seconds):
        raise PipelineError(f"timeline is {board.total_seconds:.1f}s; target {spec.target_seconds:.0f}"
                            f"±{spec.tolerance_seconds:.0f}s. Revise narration length.", retryable=False)
    stage("storyboard", "VALID", f"{len(board.scenes)} scenes, {board.total_seconds:.2f}s")

    # 4. Real 3D renders, scene by scene; unchanged scenes are reused.
    frame_dirs, render_infos = [], []
    for s in board.scenes:
        d, info, reused = render_scene(s.model_dump(), board, settings, project / "renders", log)
        frame_dirs.append(d)
        render_infos.append({**info, "reused_cached_render": reused})
        heartbeat()
    stage("render", "DONE", f"{sum(1 for r in render_infos if not r['reused_cached_render'])} rendered, "
                            f"{sum(1 for r in render_infos if r['reused_cached_render'])} reused")

    # 5. Subtitles + 6. assembly.
    srt_text = build_srt(board, spoken)
    srt = project / "exports" / "subtitles.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    srt.write_text(srt_text, encoding="utf-8")
    titles_text = build_title_srt(board)
    titles = project / "exports" / "headlines.srt"
    titles.write_text(titles_text, encoding="utf-8")
    if validate_srt(titles_text):
        raise PipelineError("headline subtitles invalid: " + "; ".join(validate_srt(titles_text)), retryable=False)
    final = project / "exports" / "final.mp4"
    edit = assemble(board, frame_dirs, wavs, srt, project / "work", final, titles)
    stage("assemble", "DONE", f"{edit['final_seconds']:.2f}s")

    # 7. QA, with one safe repair attempt: rebuild the edit from the same assets and re-check.
    qa = technical_qa(final, board, srt_text, spec.target_seconds, spec.tolerance_seconds,
                      len(edit["clips"]), project / "qa" / "frames")
    repairs = []
    if not qa["passed"]:
        failed = [c["check"] for c in qa["checks"] if c["status"] == "FAIL"]
        repairs.append({"reason": failed, "action": "re-assemble from cached renders and audio"})
        edit = assemble(board, frame_dirs, wavs, srt, project / "work", final, titles)
        qa = technical_qa(final, board, srt_text, spec.target_seconds, spec.tolerance_seconds,
                          len(edit["clips"]), project / "qa" / "frames")
        repairs[-1]["result"] = "PASS" if qa["passed"] else "STILL FAILING"
    (project / "qa" / "qa_report.json").write_text(json.dumps(qa, indent=2, ensure_ascii=False))
    stage("qa", "PASS" if qa["passed"] else "FAIL", f"technical score {qa['technical_score']}")
    if not qa["passed"]:
        raise PipelineError("QA failed after repair: " + ", ".join(
            c["check"] for c in qa["checks"] if c["status"] == "FAIL"), retryable=False)

    # 8. Platform metadata and 9. production manifest.
    metadata = {"title": script.title, "caption": script.caption, "hashtags": script.hashtags,
                "thumbnail_concept": script.thumbnail_concept, "language": spec.language,
                "platform": spec.platform, "aspect_ratio": spec.aspect_ratio}
    (project / "exports" / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    manifest = {
        "apex_version": __version__,
        "spec": spec.model_dump(),
        "script": {"version": script.version_hash, "provenance": script.provenance, "review_log": review_log,
                   "lock": lock},
        "content_type": "real 3D rendered content (procedural scenes, Blender Cycles path tracing)",
        "render": {"settings": {**asdict(settings), "blender_python": "<local>"}, "scenes": render_infos},
        "audio": {"tts_provider": tts.name, "tts_quality": tts.quality_note, "music": edit["music_source"],
                  "loudness_target_lufs": -14},
        "storyboard": str(project / "storyboard.json"),
        "outputs": {name: {"path": str(p), "sha256": _file_sha(Path(p)), "bytes": Path(p).stat().st_size}
                    for name, p in {"final_video": final, "subtitles": srt,
                                    "metadata": project / "exports" / "metadata.json"}.items()},
        "qa": {"passed": qa["passed"], "technical_score": qa["technical_score"],
               "creative_review": qa["creative_review"], "report": str(project / "qa" / "qa_report.json")},
        "repairs": repairs,
        "stages": stages,
        "wall_clock_seconds": round(time.time() - started, 1),
    }
    (project / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest
