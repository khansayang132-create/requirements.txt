"""Frame-by-frame and second-by-second audit of a finished video, plus a real playback test in Chromium.

    python -m agency audit-media PATH [--out report.json] [--no-playback]

Every frame is decoded (downscaled to 96 px wide grey for speed) and measured:
  Windows a production declares as intended (fades, title/credit cards: see expected_from_edit) are listed under
  `expected` instead of failing; nothing is dropped from the report.
  black      mean luminance < 12            (fade-to-black frames at the very start/end are allowed: <= 1 s)
  blank      luminance std-dev < 2.5        (a flat frame: nothing drawn)
  frozen     a run of >= 3 s in which fewer than 3 pixels (of the 96-px-wide grey frame) change by > 10 levels
             between each frame and the frame 0.5 s later (slow motion is invisible frame-to-frame at this
             scale). Compression noise moves pixels by a few levels; a blinking eye or a lifted arm in a wide
             shot moves a handful by far more (a mean-difference threshold misread ep005's calm wide shot
             as frozen, so the test counts changed pixels instead of averaging them away)
  glitch     a single-frame jump > 4x the median frame difference AND > 40, that does not persist (scene cuts
             persist; a one-frame flash does not)
Audio, per 100 ms window: RMS dBFS, peak; flags clipping (samples at full scale), silence runs >= 2 s (below
-55 dBFS) away from the head and tail, and reports integrated loudness (EBU R128) and true peak.
Playback: the file is opened in headless Chromium in a <video> element and played; PASS needs no media error,
readyState >= 3 and currentTime advancing by >= 1 s.
NOT measured: whether it looks or sounds good. Contact sheets for a person are written next to the report.
"""
from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np

W = 96


def _probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def frames(path: Path, width: int, height: int) -> np.ndarray:
    h = round(height * W / width / 2) * 2
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={W}:{h}", "-f", "rawvideo", "-pix_fmt", "gray",
                          "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, W).astype(np.float32)


def audio(path: Path, sr: int = 24000) -> np.ndarray:
    """(samples, channels) at the file's own channel count: a mono downmix would sum channels and fake clipping."""
    info = _probe(path)
    ch = next(int(s.get("channels", 1)) for s in info["streams"] if s["codec_type"] == "audio")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, ch)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, start = [], None
    for i, m in enumerate([*list(mask), False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((start, i))
            start = None
    return out


def playback(path: Path) -> dict:
    script = r"""
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file://' + process.argv[1]);           // the browser's own video document (a page can't load file://)
  const r = await p.evaluate(async () => {
    const v = document.querySelector('video'); v.muted = true;
    await new Promise((res) => { v.oncanplay = res; v.onerror = res; setTimeout(res, 15000); });
    if (v.error) return { error: v.error.code };
    v.pause(); v.currentTime = 0;                       // the media page autoplays; a short clip may have ended
    await new Promise((res) => { v.onseeked = res; setTimeout(res, 3000); });
    const t0 = v.currentTime; await v.play().catch(e => null);
    await new Promise(r => setTimeout(r, 2500));
    return { readyState: v.readyState, duration: v.duration, advanced: v.currentTime - t0, w: v.videoWidth, h: v.videoHeight };
  });
  console.log(JSON.stringify(r)); await b.close();
})();"""
    r = subprocess.run(["node", "-e", script, str(path.resolve())], capture_output=True, text=True, timeout=120)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"status": "BLOCKED", "detail": (r.stderr or r.stdout)[-300:]}
    ok = "error" not in res and res.get("readyState", 0) >= 3 and res.get("advanced", 0) >= 1.0
    return {"status": "PASS" if ok else "FAIL"} | res


def expected_from_edit(report: dict, fade_s: float = 0.4) -> list[dict]:
    """Intended dark frames and stills declared by an edit: the dip to black at every segment boundary and the
    title/credits cards, which are still pictures by design."""
    out, t = [], 0.0
    for name, dur in report["segments"]:
        if t > 0:
            out.append({"start_s": t - fade_s, "end_s": t + fade_s, "kind": "black",
                        "reason": f"fade between segments at {t:.2f}s"})
        if name in ("title", "credits"):
            out.append({"start_s": t, "end_s": t + dur, "kind": "still", "reason": f"{name} card"})
        t += dur
    return out


def audit(path: Path, need_audio: bool = True, do_playback: bool = True, expected: list[dict] | None = None) -> dict:
    """`expected`: windows a production declares as intended ({start_s, end_s, kind: black|still, reason}). A run
    wholly inside a window of its kind is listed under `expected`, not counted as a problem; nothing is dropped."""
    path = Path(path)
    info = _probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    fps = float(Fraction(v["r_frame_rate"]))
    f = frames(path, int(v["width"]), int(v["height"]))
    n = len(f)
    mean, std = f.mean(axis=(1, 2)), f.std(axis=(1, 2))
    diff = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2)) if n > 1 else np.zeros(0)
    edge = round(fps)                                          # fades allowed in the first/last second
    black = [(a, b) for a, b in _runs(mean < 12) if not (a < edge or b > n - edge)]
    blank = [(a, b) for a, b in _runs(std < 2.5) if not (a < edge or b > n - edge)]
    k = max(1, round(fps / 2))                                 # compare each frame with the one 0.5 s later
    moved = np.array([(np.abs(f[i + k] - f[i]) > 10).sum() for i in range(n - k)]) if n > k else np.zeros(0)
    frozen = [(a, b + k) for a, b in _runs(moved < 3) if (b + k - a) >= 3 * fps]
    allowed = []

    def unexpected(runs, kinds):
        keep = []
        for a, b in runs:
            w = next((e for e in expected or [] if e["kind"] in kinds and a / fps >= e["start_s"] - 1 / fps
                      and b / fps <= e["end_s"] + 1 / fps), None)
            if w:
                allowed.append({"frames": [a, b], "reason": w["reason"]})
            else:
                keep.append((a, b))
        return keep
    black, blank = unexpected(black, ("black",)), unexpected(blank, ("black",))
    frozen = unexpected(frozen, ("still",))
    med = float(np.median(diff)) if len(diff) else 0.0
    glitch = []
    for i in range(1, len(diff) - 1):
        if diff[i] > max(40, 4 * med) and diff[i + 1] > max(40, 4 * med) * 0.8:   # out and straight back = a flash
            if np.abs(f[i + 2] - f[i]).mean() < diff[i] * 0.3:
                glitch.append(i + 1)
    rep: dict = {"file": str(path), "bytes": path.stat().st_size, "fps": fps, "frames_decoded": n,
                 "frames_declared": int(v.get("nb_frames") or 0), "resolution": [int(v["width"]), int(v["height"])],
                 "video": {"black_runs": black, "blank_runs": blank, "frozen_runs_over_3s": frozen,
                           "flash_glitches": glitch, "median_frame_change": round(med, 2)},
                 "expected": allowed}
    problems = []
    if rep["frames_declared"] and abs(n - rep["frames_declared"]) > 1:
        problems.append(f"decoded {n} frames, container says {rep['frames_declared']}")
    for k in ("black_runs", "blank_runs", "frozen_runs_over_3s", "flash_glitches"):
        if rep["video"][k]:
            problems.append(f"{k}: {rep['video'][k][:5]}")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    if need_audio and not has_audio:
        problems.append("no audio stream")
    if has_audio:
        a2 = audio(path)
        clip = int((np.abs(a2) >= 0.999).sum())                     # per channel, per sample
        a = a2.mean(axis=1)                                         # loudness windows on the channel average
        win = 2400                                                  # 100 ms at 24 kHz
        k = len(a) // win
        blocks = a[: k * win].reshape(k, win)
        rms = 20 * np.log10(np.sqrt((blocks ** 2).mean(axis=1)) + 1e-9)
        silent = [(s / 10, e / 10) for s, e in _runs(rms < -55) if (e - s) >= 20 and s > 10 and e < k - 10]
        lr = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null",
                             "-"], capture_output=True, text=True).stderr
        i_lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", lr)
        tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", lr)
        rep["audio"] = {"seconds": round(len(a) / 24000, 3), "silent_runs_s": silent, "clipped_samples": clip,
                        "integrated_lufs": float(i_lufs[-1]) if i_lufs else None, "true_peak_dbfs": float(tp[-1]) if tp else None,
                        "rms_dbfs_median": round(float(np.median(rms)), 1)}
        if silent:
            problems.append(f"silence runs (s): {silent[:5]}")
        if clip > 0:
            problems.append(f"{clip} clipped samples")
        dur_v = n / fps
        if abs(rep["audio"]["seconds"] - dur_v) > 0.15:
            problems.append(f"audio {rep['audio']['seconds']}s vs video {dur_v:.3f}s")
    if do_playback:
        rep["playback"] = playback(path)
        if rep["playback"]["status"] != "PASS":
            problems.append(f"playback {rep['playback']}")
    rep["status"] = "FAIL" if problems else "PASS"
    rep["problems"] = problems
    rep["not_measured"] = "visual and audio quality as a person judges them (see the contact sheets)"
    return rep


def contact_sheets(path: Path, out_dir: Path, every_s: float = 2.0, cols: int = 6) -> list[Path]:
    """Frames every `every_s` seconds through the whole video, tiled into sheets of cols x 4 for a person to review."""
    out_dir.mkdir(parents=True, exist_ok=True)
    info = _probe(path)
    dur = float(info["format"]["duration"])
    per = cols * 4
    sheets = []
    for k, start in enumerate(np.arange(0, dur, every_s * per)):
        o = out_dir / f"sheet_{k + 1:02d}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{every_s * per:.2f}", "-i", str(path),
                        "-vf", f"fps=1/{every_s},scale=320:-1,drawtext=text='%{{pts\\:hms\\:{start:.2f}}}':x=6:y=6:fontsize=18:"
                               f"fontcolor=white:box=1:boxcolor=black@0.5,tile={cols}x4", "-frames:v", "1", "-q:v", "4", str(o)],
                       check=True)
        sheets.append(o)
    return sheets
