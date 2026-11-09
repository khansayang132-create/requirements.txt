#!/usr/bin/env python3
"""Validate an SRT/VTT file locally and upload it as a caption track (captions.insert),
or replace an existing track's content (captions.update). Writes need --confirm.

Quota: captions.insert = 400 units, captions.update = 450 units.

Examples:
  python skills/youtube-transcript/scripts/upload_captions.py --file data/transcripts/a.srt --validate-only
  python skills/youtube-transcript/scripts/upload_captions.py --file a.srt --convert vtt --out a.vtt
  python skills/youtube-transcript/scripts/upload_captions.py --video-id ID --file a.srt --language id --name "Bahasa Indonesia" --confirm
  python skills/youtube-transcript/scripts/upload_captions.py --update TRACK_ID --file a.srt --confirm
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.captions import convert, validate_caption_file  # noqa: E402
from src.exceptions import ValidationError  # noqa: E402
from src.safety import DRY_RUN, decide_mode  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", required=True, help="SRT or VTT caption file")
    p.add_argument("--validate-only", action="store_true")
    p.add_argument("--convert", choices=["srt", "vtt"], help="Convert the file locally and write --out")
    p.add_argument("--out")
    p.add_argument("--video-id", help="Video to add a new caption track to")
    p.add_argument("--update", metavar="TRACK_ID", help="Replace the content of this existing track")
    p.add_argument("--language", default="id", help="BCP-47 language of the track (default id)")
    p.add_argument("--name", default="", help="Track name shown to viewers")
    p.add_argument("--draft", action="store_true", help="Upload as a draft (not visible to viewers)")
    cli.add_safety_flags(p)
    cli.add_output_flags(p)
    args = p.parse_args()

    report = validate_caption_file(args.file)
    if not report.ok:
        raise ValidationError(f"Caption file {args.file} is invalid", report.errors)

    if args.convert:
        if not args.out:
            p.error("--convert needs --out")
        Path(args.out).write_text(convert(args.file, args.convert), encoding="utf-8")
        cli.emit({"converted": args.out, "format": args.convert, "report": report.as_dict()}, args.json, lambda d: f"Wrote {d['converted']}")
        return 0
    if args.validate_only or not (args.video_id or args.update):
        cli.emit(report.as_dict(), args.json, lambda d: f"Valid caption file: {d['info']}" + "".join(f"\nwarning: {w}" for w in d["warnings"]))
        return 0

    rt = cli.runtime()
    op = "captions.update" if args.update else "captions.insert"
    mode = decide_mode(dry_run=args.dry_run, confirm=args.confirm, action="write a caption track")
    if mode == DRY_RUN:
        cli.emit({"mode": "dry_run", "would_call": [op], "video_id": args.video_id, "track_id": args.update, "language": args.language,
                  "report": report.as_dict(), "quota_estimate": rt.quota.estimate([op]).by_bucket}, True)
        return 0
    rt.quota.check([op])
    client = cli.make_client(rt, [op])
    if args.update:
        resp = client.update_caption(args.update, path=args.file, is_draft=args.draft if args.draft else None)
    else:
        resp = client.insert_caption(args.video_id, args.language, args.name, args.file, is_draft=args.draft)
    cli.emit({"mode": "execute", "operation": op, "track": resp}, args.json, lambda d: f"{op} OK: track {d['track'].get('id')}")
    return 0


if __name__ == "__main__":
    cli.run(main)
