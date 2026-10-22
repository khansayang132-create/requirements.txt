"""Integration tests with real ffmpeg / espeak-ng / Blender (skipped where a tool is missing)."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from apex.assemble import assemble
from apex.media import ffprobe, probe_duration, run_ffmpeg
from apex.models import Script
from apex.pipeline import RenderSettings, render_scene
from apex.qa import technical_qa
from apex.storyboard import build_storyboard
from apex.subtitles import build_srt, build_title_srt

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
needs_espeak = pytest.mark.skipif(not shutil.which("espeak-ng"), reason="espeak-ng not installed")
needs_bpy = pytest.mark.skipif(importlib.util.find_spec("bpy") is None, reason="bpy not installed")

APEX_ROOT = Path(__file__).resolve().parent.parent


def two_scene_script() -> Script:
    return Script.model_validate({
        "title": "Test", "concept": "test concept", "hook": "hook line",
        "provenance": "test fixture",
        "scenes": [
            {"scene_id": "s01", "purpose": "hook", "narration": "satu dua tiga", "on_screen_text": "SATU",
             "template": "hero_coin", "camera_move": "static"},
            {"scene_id": "s02", "purpose": "end", "narration": "empat lima enam", "on_screen_text": "DUA",
             "template": "coin_stack", "camera_move": "dolly_in"},
        ]})


def fake_frames(d: Path, seconds: float, fps: int, color: str) -> Path:
    d.mkdir(parents=True)
    run_ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size=432x768:rate={fps}:duration={seconds}",
                "-vf", f"drawbox=c={color}@0.4:t=fill", str(d / "frame_%04d.png")])
    return d


def tone(path: Path, seconds: float, freq: int) -> Path:
    run_ffmpeg(["-f", "lavfi", "-i", f"sine=f={freq}:d={seconds}", "-ar", "44100", str(path)])
    return path


@needs_ffmpeg
def test_assemble_and_qa_pass_on_good_video(tmp_path):
    fps = 12
    wavs = [tone(tmp_path / "a.wav", 1.6, 440), tone(tmp_path / "b.wav", 1.8, 550)]
    spoken = [probe_duration(w) for w in wavs]
    board = build_storyboard(two_scene_script(), spoken, "9:16", fps)
    frames = [fake_frames(tmp_path / f"f{i}", s.duration, fps, c)
              for i, (s, c) in enumerate(zip(board.scenes, ["red", "blue"]))]
    srt_text = build_srt(board, spoken)
    srt = tmp_path / "s.srt"
    srt.write_text(srt_text)
    titles = tmp_path / "t.srt"
    titles.write_text(build_title_srt(board))
    out = tmp_path / "final.mp4"
    edit = assemble(board, frames, wavs, srt, tmp_path / "work", out, titles)
    info = ffprobe(out)
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    qa = technical_qa(out, board, srt_text, board.total_seconds, 0.5, len(edit["clips"]), tmp_path / "qa")
    failed = [c for c in qa["checks"] if c["status"] == "FAIL"]
    assert qa["passed"], failed
    assert qa["creative_review"]["status"] == "NOT RUN"
    assert len(qa["sampled_frames"]) == 2


@needs_ffmpeg
def test_qa_detects_black_video_and_missing_audio(tmp_path):
    board = build_storyboard(two_scene_script(), [3.0, 3.0], "9:16", 12)
    out = tmp_path / "bad.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", f"color=c=black:s=432x768:r=12:d={board.total_seconds}",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", str(out)])
    qa = technical_qa(out, board, build_srt(board, [3.0, 3.0]), board.total_seconds, 1, 2, tmp_path / "qa")
    status = {c["check"]: c["status"] for c in qa["checks"]}
    assert not qa["passed"]
    assert status["has_audio_stream"] == "FAIL"
    assert status["no_unexpected_black"] == "FAIL"


@needs_ffmpeg
def test_qa_reports_missing_file(tmp_path):
    board = build_storyboard(two_scene_script(), [3.0, 3.0], "9:16", 12)
    qa = technical_qa(tmp_path / "nope.mp4", board, "", 6, 1, 2, tmp_path / "qa")
    assert not qa["passed"] and qa["technical_score"] == 0.0


@needs_espeak
def test_espeak_produces_indonesian_audio(tmp_path):
    from apex.tts import EspeakProvider
    wav = EspeakProvider().synthesize("Rp25.000 setiap hari", "id", tmp_path / "x.wav")
    assert probe_duration(wav) > 1.0


def test_cached_render_is_reused_without_running_blender(tmp_path):
    board = build_storyboard(two_scene_script(), [3.0, 3.0], "9:16", 2)
    scene = board.scenes[0].model_dump()
    settings = RenderSettings(fps=2, samples=1, blender_python="/nonexistent/python")
    from apex.pipeline import RENDERER_SOURCE, _file_sha, _sha
    from apex import __version__
    key = _sha(scene["template"], scene["camera_move"], scene["params"], scene["duration"], board.fps,
               board.width, board.height, settings.samples, __version__, _file_sha(RENDERER_SOURCE))
    d = tmp_path / f"{scene['scene_id']}_{key}"
    d.mkdir()
    for i in range(1, round(scene["duration"] * 2) + 1):
        (d / f"frame_{i:04d}.png").write_bytes(b"png")
    (d / "render_info.json").write_text(json.dumps({"scene_id": "s01"}))
    out, info, reused = render_scene(scene, board, settings, tmp_path, print)
    assert reused and out == d


@needs_bpy
def test_blender_renders_real_frames(tmp_path):
    scene = {"scene_id": "t", "template": "piggy_bank", "camera_move": "orbit_left", "duration": 1.0,
             "params": {"coins": 2}}
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps(scene))
    p = subprocess.run([sys.executable, "-m", "apex.render3d", str(spec), str(tmp_path / "out"),
                        "--fps", "2", "--width", "108", "--height", "192", "--samples", "1"],
                       cwd=APEX_ROOT, capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stderr[-800:]
    frames = sorted((tmp_path / "out").glob("frame_*.png"))
    assert len(frames) == 2
    info = json.loads((tmp_path / "out" / "render_info.json").read_text())
    assert info["engine"] == "CYCLES (CPU)" and info["frames"] == 2
