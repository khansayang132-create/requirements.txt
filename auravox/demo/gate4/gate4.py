"""Gate 4: AURAVOX dialogue -> HUMANVERSE Blender scene with phoneme lip sync -> playable MP4 (with checks).

Usage (from the repo root):
  AVX_HOME=auravox/data auravox/.venv/bin/python auravox/demo/gate4/gate4.py [--production gate2] [--scene S01]
      [--res 960x540] [--samples 4] [--threads 2]

Steps: export the production's lines in HUMANVERSE's lines.json schema; write a scene spec (three approved
HUMANVERSE characters, idle + looks + `say` events at the exact dialogue times); build the .blend with
HUMANVERSE's build_scene.py; render every frame with render.py (resumable); mux with the AURAVOX master audio;
verify the MP4 with ffprobe and write gate4_report.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HV = REPO / "humanverse"
BL = HV / ".claude/skills/humanverse-studio/scripts/blender"
BPY = HV / ".venv/bin/python"
FPS = 24
BASE = {"calm": "neutral", "whisper": "neutral"}         # AURAVOX emotions HUMANVERSE has no face for
CAMERA = {1: {"loc": [0.0, -1.9, 1.42], "target": [0.0, 0.0, 1.3], "lens": 50, "focus": [0, 0, 1.35]},   # head and shoulders
          2: {"loc": [0.0, -2.8, 1.32], "target": [0.0, 0.0, 1.15], "lens": 40, "focus": [0, 0, 1.25]},
          3: {"loc": [0.0, -3.3, 1.3], "target": [0.0, 0.0, 1.12], "lens": 38, "focus": [0, 0, 1.2]}}
def camera(speakers, char_dir: Path) -> dict:
    """Single speaker: frame head and shoulders from the character's measured height (its build report), so a tall
    adult and a small child both fill the shot with eye-room above. Groups use the fixed wider framings."""
    cam = dict(CAMERA[len(speakers)])
    rep = char_dir / speakers[0] / "build_report.json"
    if len(speakers) == 1 and rep.is_file():
        h = json.loads(rep.read_text())["height_m"]
        eye = 0.91 * h                                        # eye line of these rigs, measured from the build
        cam = {"loc": [0.0, -1.75, round(eye + 0.06, 3)], "target": [0.0, 0.0, round(eye - 0.04, 3)], "lens": 50,
               "focus": [0, 0, round(eye, 3)]}
    return cam


LEAD = 0.5                                                   # master.wav starts the dialogue 0.5 s in


def run(cmd, log):
    with open(log, "a") as f:
        f.write("$ " + " ".join(map(str, cmd)) + "\n")
        p = subprocess.run(list(map(str, cmd)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        f.write(p.stdout)
    if p.returncode or "Traceback" in p.stdout:
        sys.exit(f"FAIL {cmd[1] if len(cmd) > 1 else cmd[0]}: see {log}\n" + "\n".join(p.stdout.splitlines()[-10:]))
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--production", default="gate2")
    ap.add_argument("--scene", default="S01")
    ap.add_argument("--res", default="960x540")
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--out", default="", help="output folder (default $AVX_HOME/gate4)")
    ap.add_argument("--min-speakers", type=int, default=3)
    ap.add_argument("--character-dir", default=str(HV / "project/characters"), help="folder of approved <ID>/<ID>.blend")
    ap.add_argument("--preview", default="", help="render only these frames (e.g. 1,120) to check framing, then stop")
    a = ap.parse_args()

    sys.path.insert(0, str(REPO / "auravox/src"))
    from auravox import production
    from auravox.studio import Studio

    st = Studio(Path(os.environ.get("AVX_HOME", REPO / "auravox/data")))
    prod = st.home / "productions" / a.production
    meta = json.loads((prod / "dialogue.json").read_text())
    out = Path(a.out) if a.out else st.home / "gate4"
    (out / "frames").mkdir(parents=True, exist_ok=True)
    log = out / "gate4.log"

    lines = [ln for ln in meta["lines"] if ln.get("scene_id") == a.scene]
    if len({ln["character_id"] for ln in lines}) < a.min_speakers:
        sys.exit(f"BLOCKED: scene {a.scene} of {a.production} has fewer than {a.min_speakers} speakers")
    lines_json = production.export_humanverse_lines({"lines": lines}, out / "lines.json")

    t0 = lines[0]["start_s"]
    end_s = max(ln["start_s"] + ln["duration_s"] for ln in lines) - t0
    frames = int((end_s + 2 * LEAD + 0.6) * FPS)
    speakers = list(dict.fromkeys(ln["character_id"] for ln in lines))
    if len(speakers) > 3:
        sys.exit("BLOCKED: this scene layout frames at most 3 speakers")
    layout = {1: ((0.0,), (0,)), 2: ((-0.6, 0.6), (12, -12)), 3: ((-1.1, 0.0, 1.1), (18, 0, -18))}[len(speakers)]
    xs = dict(zip(speakers, layout[0]))
    heading = dict(zip(speakers, layout[1]))
    chars = [{"id": c, "start": [xs[c], 0.0, heading[c]], "expression": "neutral",
              "blend": str(Path(a.character_dir) / c / f"{c}.blend")} for c in speakers]
    perf = [{"char": c, "op": "idle", "f0": 1, "f1": frames, "energy": 0.5} for c in speakers]
    for ln in lines:
        f = int(round((ln["start_s"] - t0 + LEAD) * FPS)) + 1
        perf.append({"char": ln["character_id"], "op": "say", "line_id": ln["line_id"], "f": f, "base": BASE.get(ln.get("emotion"), ln.get("emotion", "neutral")),
                     "gesture": True})
        for c in speakers:                                     # listeners turn their heads to whoever speaks
            if c != ln["character_id"]:
                yaw = 30 if xs[ln["character_id"]] > xs[c] else -30
                perf.append({"char": c, "op": "look", "f": max(1, f - 4), "yaw": yaw, "pitch": 0})
    w, h = map(int, a.res.split("x"))
    spec = {"scene_id": f"AVX_{a.scene}", "environment": "park", "seed": 3, "frames": frames, "light_center": [0, 0, 0.9],
            "characters": chars, "performance": perf, "props": [], "fps": FPS, "resolution": [w, h], "samples": a.samples,
            "shots": [{"shot_id": "AVX_SH01", "f0": 1, "f1": frames,
                       "cam": camera(speakers, Path(a.character_dir))}]}
    (out / "spec.json").write_text(json.dumps(spec, indent=2))

    blend = out / "scene.blend"
    if not blend.exists():
        run([BPY, BL / "build_scene.py", "--", "--spec", out / "spec.json", "--lines", lines_json, "--out", blend,
             "--report", out / "scene_report.json"], log)
    if a.preview:
        run([BPY, BL / "render.py", "--", "--blend", blend, "--out", out / "preview", "--frames", a.preview, "--samples", a.samples,
             "--threads", a.threads], log)
        return print("preview frames in", out / "preview")
    have = {int(p.stem) for p in (out / "frames").glob("*.png") if p.stat().st_size > 0}
    todo = [f for f in range(1, frames + 1) if f not in have]
    for i in range(0, len(todo), 24):
        part = todo[i:i + 24]
        run([BPY, BL / "render.py", "--", "--blend", blend, "--out", out / "frames", "--frames", ",".join(map(str, part)),
             "--samples", a.samples, "--threads", a.threads], log)
        print(f"rendered {part[-1]}/{frames}", flush=True)

    audio = out / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{frames / FPS:.3f}", "-i", str(prod / "master.wav"),
                    "-af", "apad,afade=t=out:st=%.2f:d=0.5" % (frames / FPS - 0.5), "-t", f"{frames / FPS:.3f}", str(audio)], check=True)
    # audio is padded with silence to exactly the rendered length, so no rendered frame is ever cut
    mp4 = out / f"{'gate4_' if not a.out else ''}{a.production}_{a.scene}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(out / "frames/%04d.png"), "-i", str(audio),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-t", f"{frames / FPS:.3f}",
                    "-movflags", "+faststart", str(mp4)], check=True)
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(mp4)],
                                      capture_output=True, text=True, check=True).stdout)
    decode = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-f", "null", "-"], capture_output=True, text=True)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    scene_rep = json.loads((out / "scene_report.json").read_text())
    checks = {"enough_speakers": len(speakers) >= a.min_speakers, "video_and_audio_streams": {s["codec_type"] for s in probe["streams"]} == {"video", "audio"},
              "decodes_without_errors": decode.returncode == 0 and not decode.stderr.strip(),
              "frame_count": int(v["nb_frames"]) == frames,
              "lipsync_keyed_every_line": sum(c.get("type") == "dialogue" for c in scene_rep.get("cues", [])) == len(lines) and all(c.get("visemes_keyed", 0) >= 3 for c in scene_rep.get("cues", []) if c.get("type") == "dialogue")}
    rep = {"status": "PASS" if all(checks.values()) else "FAIL", "mp4": str(mp4), "checks": checks, "frames": frames,
           "duration_s": float(probe["format"]["duration"]), "resolution": [v["width"], v["height"]], "speakers": speakers,
           "lines": [ln["line_id"] for ln in lines], "lip_sync": "phoneme timings from AURAVOX takes keyed as visemes by HUMANVERSE",
           "not_tested": "perceptual lip-sync and acting quality (needs a person to watch)"}
    (out / "gate4_report.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
