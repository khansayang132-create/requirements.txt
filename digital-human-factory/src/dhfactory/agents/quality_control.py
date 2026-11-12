from __future__ import annotations

import json
import re
from pathlib import Path

from ..media import ffmpeg, ffprobe
from ..state import ProductionState
from .base import AgentResult, BaseAgent


def check_video(path: Path, *, width: int, height: int, duration_target: float | None, tolerance: float = 0.10, mock: bool = False) -> dict:
    checks: dict[str, dict] = {}

    def put(name: str, status: str, detail: str) -> None:
        checks[name] = {"status": status, "detail": detail}

    if not path.is_file() or path.stat().st_size == 0:
        put("file_exists", "FAIL", f"{path} missing or empty")
        return {"checks": checks, "overall": "FAIL"}
    put("file_exists", "PASS", f"{path.stat().st_size} bytes")
    info = ffprobe.probe(path)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"].get("duration", 0))
    put("video_stream", "PASS" if v else "FAIL", v["codec_name"] if v else "none")
    put("audio_stream", "PASS" if a else "FAIL", f"{a['codec_name']} {a.get('sample_rate')} Hz" if a else "none")
    if v:
        put("resolution", "PASS" if (v["width"], v["height"]) == (width, height) else "FAIL", f"{v['width']}x{v['height']} (want {width}x{height})")
        frames = v.get("nb_frames")
        put("frame_count", "PASS" if frames and int(frames) > 0 else "FAIL", str(frames))
    if duration_target:
        ok = abs(dur - duration_target) <= duration_target * tolerance
        put("duration", "PASS" if ok else "FAIL", f"{dur:.2f}s (target {duration_target:g}s ±{tolerance:.0%})")
    if v and a:
        dv, da = float(v.get("duration", dur)), float(a.get("duration", dur))
        put("av_length_sync", "PASS" if abs(dv - da) <= 0.1 else "FAIL", f"video {dv:.2f}s / audio {da:.2f}s")
    errs = ffprobe.decode_errors(path)
    put("playback_decode", "PASS" if not errs else "FAIL", "full decode, no errors" if not errs else errs[:200])
    if a:
        proc = __import__("subprocess").run([ffmpeg.binary(), "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                                            capture_output=True, text=True)
        m = re.search(r"Integrated loudness:\s+I:\s+(-?[\d.]+) LUFS", proc.stderr)
        lufs = float(m.group(1)) if m else None
        put("loudness", "PASS" if lufs is not None and abs(lufs + 14) <= 2 else "FAIL", f"{lufs} LUFS (target -14)")
    put("real_production", "BLOCKED" if mock else "PASS", "made with the MOCK provider: placeholder, not a presenter" if mock else "provider-generated")
    put("lip_sync_visual", "NOT_TESTED", "no automatic mouth-to-audio scorer is installed; watch the file (provider lip sync is recorded in metadata)")
    overall = "FAIL" if any(c["status"] == "FAIL" for c in checks.values()) else ("BLOCKED" if mock else "PASS")
    return {"checks": checks, "overall": overall, "probe": {"duration": dur, "size": int(info["format"].get("size", 0))}}


class QualityControlAgent(BaseAgent):
    name = "quality-control"
    description = "Verifies the export with ffprobe/ffmpeg: streams, resolution, duration, full decode, A/V length, loudness, identity record."

    async def run(self, state: ProductionState, step: str) -> AgentResult:
        if not state.final_video:
            return AgentResult(status="blocked", error="no final video")
        mock = "mock" in (state.providers.get("avatar"), state.providers.get("voice"))
        report = check_video(Path(state.final_video), width=state.resolution[0], height=state.resolution[1],
                             duration_target=state.duration_target, mock=mock)
        ident = self.ctx.root / "characters" / (state.character.character_id if state.character else "-") / "identity.json"
        report["checks"]["identity_recorded"] = {"status": "PASS" if ident.is_file() else "FAIL", "detail": str(ident)}
        out = Path(state.final_video).parent / "qc_report.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        state.qc_status = report["overall"]
        status = "failed" if report["overall"] == "FAIL" else "success"
        return AgentResult(status=status, artifact_paths=[str(out)], metadata={"overall": report["overall"]},
                           error=None if status == "success" else ", ".join(k for k, c in report["checks"].items() if c["status"] == "FAIL"))
