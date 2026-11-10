#!/usr/bin/env python3
"""Compute a publish time, or schedule an existing private video (videos.update status.publishAt).

YouTube rule: publishAt only works while privacyStatus is 'private' and the video has
never been public. At that time YouTube makes it public. This script refuses to make a
currently public/unlisted video private unless --allow-unpublish is given.

Examples:
  # Just compute "tomorrow 19:00 Jakarta time" for use with upload.py --publish-at
  python skills/youtube-upload/scripts/schedule.py --tomorrow 19:00 --tz Asia/Jakarta
  # Schedule an uploaded private video
  python skills/youtube-upload/scripts/schedule.py --video-id VIDEO_ID --at 2026-11-10T19:00:00+07:00 --confirm
  # Cancel a schedule (stays private)
  python skills/youtube-upload/scripts/schedule.py --video-id VIDEO_ID --clear --confirm
"""

import argparse
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.exceptions import ValidationError  # noqa: E402
from src.safety import DRY_RUN, decide_mode  # noqa: E402
from src.uploader import merge_for_update  # noqa: E402
from src.validators import parse_publish_at, to_rfc3339_utc, validate_schedule  # noqa: E402


def resolve_time(args: argparse.Namespace, now: datetime | None = None) -> datetime:
    if args.at:
        return parse_publish_at(args.at)
    tz = ZoneInfo(args.tz)
    now = (now or datetime.now(tz)).astimezone(tz)
    hh, mm = (int(x) for x in args.tomorrow.split(":"))
    return datetime.combine(now.date() + timedelta(days=1), time(hh, mm), tzinfo=tz)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    when = p.add_mutually_exclusive_group()
    when.add_argument("--at", help="ISO-8601 time with timezone")
    when.add_argument("--tomorrow", metavar="HH:MM", help="Tomorrow at this local time (see --tz)")
    when.add_argument("--clear", action="store_true", help="Remove an existing schedule (video stays private)")
    p.add_argument("--tz", default="Asia/Jakarta", help="IANA timezone for --tomorrow (default Asia/Jakarta)")
    p.add_argument("--video-id", help="Existing video to schedule; omit to only print the computed time")
    p.add_argument("--allow-unpublish", action="store_true", help="Allow making a public/unlisted video private to schedule it")
    cli.add_safety_flags(p)
    cli.add_output_flags(p)
    args = p.parse_args()
    if not (args.at or args.tomorrow or args.clear):
        p.error("one of --at, --tomorrow or --clear is required")

    publish_at = None
    if not args.clear:
        dt = resolve_time(args)
        publish_at = to_rfc3339_utc(dt)
        r = validate_schedule(dt.isoformat(), "private")
        if not r.ok:
            raise ValidationError("Invalid schedule", r.errors)
        if not args.video_id:
            cli.emit({"publish_at_local": dt.isoformat(), "publish_at_utc": publish_at, "upload_flag": f"--privacy private --publish-at {dt.isoformat()}"}, args.json, lambda d: f"{d['publish_at_local']}  (UTC {d['publish_at_utc']})\nUse: {d['upload_flag']}")
            return 0
    elif not args.video_id:
        p.error("--clear needs --video-id")

    mode = decide_mode(dry_run=args.dry_run, confirm=args.confirm, action="change a video's publish schedule")
    rt = cli.runtime()
    client = cli.make_client(rt, ["videos.list", "videos.update"])
    current = client.get_video(args.video_id, parts="status")
    if not current:
        raise ValidationError(f"Video {args.video_id} not found on this channel")
    privacy = current["status"].get("privacyStatus")
    if privacy != "private" and not args.allow_unpublish:
        raise ValidationError(
            f"Video is currently '{privacy}'. Scheduling requires making it private first; "
            "re-run with --allow-unpublish if that is really intended."
        )
    body, diff = merge_for_update(current, {"status": {"privacyStatus": "private", "publishAt": publish_at}})
    if mode == DRY_RUN:
        cli.emit({"mode": "dry_run", "would_call": ["videos.update"], "changes": diff, "request_body": body}, True)
        return 0
    updated = client.update_video(body, "status")
    out = {"mode": "execute", "video_id": args.video_id, "changes": diff, "status": updated.get("status", {})}
    cli.emit(out, args.json, lambda d: f"Video {d['video_id']}: publishAt={d['status'].get('publishAt')} privacy={d['status'].get('privacyStatus')}")
    return 0


if __name__ == "__main__":
    cli.run(main)
