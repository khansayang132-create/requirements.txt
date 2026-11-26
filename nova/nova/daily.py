"""One-shot voiceover from the command line, for scheduled runs.

    python -m nova.daily --segments today.json --out voiceover.mp3 \
        [--preset soft-young-indonesian-woman] [--engine chatterbox-id] [--lufs -14] [--speed 1.0]

today.json is a list of scenes: [{"label": "0-2s", "text": "...", "emotion": "excitement"}, ...]
(emotion optional). A line that still contains a [placeholder] is refused: the caller must turn
it into something true first; this command never invents content. Prints a JSON summary."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from .config import Settings
from .pipeline import VALID_EMOTIONS, generate
from .profiles import PRESETS, ProfileStore


def load_segments(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("segments", [])
    if not isinstance(data, list) or not data:
        raise ValueError("segments file must hold a non-empty list of scenes")
    segs = []
    for i, s in enumerate(data):
        text = str(s.get("text", "") if isinstance(s, dict) else s).strip()
        if not text:
            continue
        if "[" in text or "]" in text:
            raise ValueError(f"scene {i + 1} still has a [placeholder]: {text[:80]}")
        emotion = s.get("emotion") if isinstance(s, dict) and s.get("emotion") in VALID_EMOTIONS else None
        segs.append({"label": str(s.get("label", f"Scene {i + 1}")) if isinstance(s, dict) else f"Scene {i + 1}",
                     "text": text, "emotion": emotion})
    if not segs:
        raise ValueError("no spoken text in the segments file")
    return segs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m nova.daily", description=__doc__.split("\n\n")[0])
    ap.add_argument("--segments", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path, help="output .mp3 or .wav")
    ap.add_argument("--preset", default="soft-young-indonesian-woman", choices=sorted(PRESETS))
    ap.add_argument("--engine", default="", help="chatterbox-id, piper, espeak-ng (default: best available)")
    ap.add_argument("--mode", default="natural", choices=["natural", "professional", "expressive"])
    ap.add_argument("--lufs", type=float, default=-14.0)
    ap.add_argument("--speed", type=float, default=1.0, help="1.2 = 20%% faster (pitch kept)")
    ap.add_argument("--pause-scale", type=float, default=1.0, help="0.6 = shorter pauses for fast TikTok pacing")
    ap.add_argument("--data-dir", type=Path, default=None, help="default: a temporary folder")
    args = ap.parse_args(argv)

    fmt = args.out.suffix.lower().lstrip(".")
    if fmt not in ("mp3", "wav"):
        ap.error("--out must end in .mp3 or .wav")
    segs = load_segments(args.segments)
    with tempfile.TemporaryDirectory() as td:
        settings = Settings()
        settings.data_dir = args.data_dir or Path(td)
        settings.ensure_dirs()
        if args.engine == "chatterbox-id":
            settings.chatterbox = True
        store = ProfileStore(settings)
        profile = store.create_designed({"preset": args.preset})
        manifest = generate(settings, store, {
            "segments": segs, "profile_id": profile["id"], "engine": args.engine or None, "mode": args.mode,
            "speed": args.speed, "pause_scale": args.pause_scale, "formats": [fmt], "target_lufs": args.lufs, "enhance": True,
        })
        args.out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(manifest["files"][fmt]["path"], args.out)
    m = manifest["mastering"]
    print(json.dumps({"out": str(args.out), "engine": manifest["engine"], "voice": profile["name"],
                      "duration_s": m["duration_s"], "lufs": m["output_lufs"], "true_peak_dbtp": m["true_peak_dbtp"],
                      "scenes": len(segs)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
