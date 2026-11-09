#!/usr/bin/env python3
"""Validate thumbnails against YouTube's rules and optionally set one on a video.

Checks (never modifies the image): JPEG/PNG by real content, <= 2 MB, width >= 640,
16:9 aspect, 1280x720 recommended, file not corrupt. --strict turns size/aspect
warnings into errors.

Examples:
  python skills/youtube-thumbnail/scripts/validate_thumbnail.py data/thumbnails/a.jpg
  python skills/youtube-thumbnail/scripts/validate_thumbnail.py data/thumbnails/*.png --strict --json
  python skills/youtube-thumbnail/scripts/validate_thumbnail.py thumb.jpg --upload --video-id ID --confirm
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.config import get  # noqa: E402
from src.exceptions import ValidationError  # noqa: E402
from src.safety import DRY_RUN, decide_mode  # noqa: E402
from src.validators import validate_thumbnail  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("images", nargs="+", help="Image file(s) to check")
    p.add_argument("--strict", action="store_true", help="Treat non-16:9 / non-1280x720 as errors")
    p.add_argument("--upload", action="store_true", help="Set the (single, valid) image as the thumbnail of --video-id")
    p.add_argument("--video-id")
    cli.add_safety_flags(p)
    cli.add_output_flags(p)
    args = p.parse_args()
    rt = cli.runtime()
    strict = args.strict or bool(get(rt.settings, "thumbnail.strict", False))

    reports = []
    for image in args.images:
        r = validate_thumbnail(image, strict=strict)
        reports.append({"file": image, **r.as_dict()})
    all_ok = all(r["ok"] for r in reports)

    if args.upload:
        if len(args.images) != 1 or not args.video_id:
            p.error("--upload needs exactly one image and --video-id")
        if not all_ok:
            raise ValidationError("Thumbnail is invalid; not uploading", reports[0]["errors"])
        mode = decide_mode(dry_run=args.dry_run, confirm=args.confirm, action="change a video's thumbnail")
        if mode == DRY_RUN:
            cli.emit({"mode": "dry_run", "would_call": ["thumbnails.set"], "video_id": args.video_id, "report": reports[0],
                      "quota_estimate": rt.quota.estimate(["thumbnails.set"]).by_bucket}, True)
            return 0
        client = cli.make_client(rt, ["thumbnails.set"])
        resp = client.set_thumbnail(args.video_id, args.images[0], reports[0]["info"]["mimetype"])
        cli.emit({"mode": "execute", "video_id": args.video_id, "thumbnails": resp.get("items", [])}, args.json,
                 lambda d: f"Thumbnail set on {d['video_id']}")
        return 0

    cli.emit({"ok": all_ok, "reports": reports}, args.json, _human)
    return 0 if all_ok else 5


def _human(d: dict) -> str:
    lines = []
    for r in d["reports"]:
        info = r["info"]
        dims = f"{info.get('width')}x{info.get('height')}" if "width" in info else "?"
        lines.append(f"{'PASS' if r['ok'] else 'FAIL'}  {r['file']}  {info.get('format', '?')} {dims} {info.get('bytes', 0) / 1024:.0f} KB")
        lines += [f"    ERROR: {e}" for e in r["errors"]] + [f"    warning: {w}" for w in r["warnings"]]
    return "\n".join(lines)


if __name__ == "__main__":
    cli.run(main)
