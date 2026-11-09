#!/usr/bin/env python3
"""Transcribe a LOCAL media file with OpenAI Whisper (runs on this machine, no API key)
when no usable caption track exists. Optional: needs `pip install -r requirements-whisper.txt`
and the ffmpeg binary. Without them it exits with code 9 and says what to install.

Use only on media you have the right to transcribe (your own uploads).

Examples:
  python skills/youtube-transcript/scripts/whisper_fallback.py --check
  python skills/youtube-transcript/scripts/whisper_fallback.py --media data/videos/clip.mp4 --language id --format srt --out data/transcripts/clip.srt
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.captions import format_srt, format_vtt, transcribe_with_whisper, validate_cues, whisper_available  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="Only report whether Whisper + ffmpeg are available")
    p.add_argument("--media", help="Local audio/video file")
    p.add_argument("--model", default="base", help="Whisper model: tiny, base, small, medium, large (default base)")
    p.add_argument("--language", help="Spoken language code, e.g. id or en (default: auto-detect)")
    p.add_argument("--format", choices=["srt", "vtt"], default="srt")
    p.add_argument("--out", help="Output caption file (default data/transcripts/<media>.<format>)")
    cli.add_output_flags(p)
    args = p.parse_args()

    ok, why = whisper_available()
    if args.check:
        cli.emit({"available": ok, "detail": why}, args.json, lambda d: f"Whisper available: {d['available']} ({d['detail']})")
        return 0 if ok else 9
    if not args.media:
        p.error("--media is required (or use --check)")

    cues = transcribe_with_whisper(args.media, model=args.model, language=args.language)
    report = validate_cues(cues)
    text = format_vtt(cues) if args.format == "vtt" else format_srt(cues)
    out = Path(args.out) if args.out else ROOT / "data" / "transcripts" / f"{Path(args.media).stem}.{args.format}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    cli.emit({"file": str(out), "cues": len(cues), "report": report.as_dict(), "engine": f"whisper:{args.model}"}, args.json,
             lambda d: f"Wrote {d['cues']} cues to {d['file']} (machine transcription: review before publishing)")
    return 0


if __name__ == "__main__":
    cli.run(main)
