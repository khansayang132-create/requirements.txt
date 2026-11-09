#!/usr/bin/env python3
"""Update an existing video's metadata/privacy, or delete it. All writes need --confirm.

videos.update replaces whole parts, so this script first reads the current snippet/status
and sends every existing field back with your changes (nothing is silently cleared).

Delete needs --delete --confirm AND --confirm-delete repeating the video ID.

Examples:
  python skills/youtube-upload/scripts/update_video.py --video-id ID --title "Judul baru" --dry-run
  python skills/youtube-upload/scripts/update_video.py --video-id ID --privacy unlisted --confirm
  python skills/youtube-upload/scripts/update_video.py --video-id ID --metadata metadata.json --confirm
  python skills/youtube-upload/scripts/update_video.py --video-id ID --delete --confirm-delete ID --confirm
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.config import load_yaml_file  # noqa: E402
from src.exceptions import ConfirmationRequired, ValidationError  # noqa: E402
from src.safety import DRY_RUN, decide_mode  # noqa: E402
from src.uploader import merge_for_update  # noqa: E402
from src.validators import ValidationResult, validate_category, validate_description, validate_privacy, validate_tags, validate_title  # noqa: E402


def changes_from_args(args: argparse.Namespace) -> tuple[dict, ValidationResult]:
    snippet: dict = {}
    status: dict = {}
    if args.metadata:
        meta = load_yaml_file(args.metadata)
        for src_key, dst in (("title", "title"), ("description", "description"), ("tags", "tags"), ("category_id", "categoryId")):
            if meta.get(src_key) is not None:
                snippet[dst] = str(meta[src_key]) if dst == "categoryId" else meta[src_key]
    if args.title is not None:
        snippet["title"] = args.title
    if args.description_file:
        snippet["description"] = Path(args.description_file).read_text(encoding="utf-8")
    elif args.description is not None:
        snippet["description"] = args.description
    if args.tags is not None:
        snippet["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.category_id is not None:
        snippet["categoryId"] = str(args.category_id)
    if args.privacy is not None:
        status["privacyStatus"] = args.privacy
        status["publishAt"] = None  # an explicit privacy change cancels any schedule
    if args.made_for_kids is not None:
        status["selfDeclaredMadeForKids"] = args.made_for_kids

    r = ValidationResult()
    if "title" in snippet:
        r.merge(validate_title(snippet["title"]))
    if "description" in snippet:
        r.merge(validate_description(snippet["description"]))
    if "tags" in snippet:
        r.merge(validate_tags(snippet["tags"]))
    if "categoryId" in snippet:
        r.merge(validate_category(snippet["categoryId"]))
    if "privacyStatus" in status:
        r.merge(validate_privacy(status["privacyStatus"]))
    changes = {}
    if snippet:
        changes["snippet"] = snippet
    if status:
        changes["status"] = status
    return changes, r


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video-id", required=True)
    p.add_argument("--metadata", help="YAML/JSON with title/description/tags/category_id")
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--description-file")
    p.add_argument("--tags", help="Comma-separated; replaces all tags")
    p.add_argument("--category", dest="category_id")
    p.add_argument("--privacy", choices=["private", "unlisted", "public"])
    kids = p.add_mutually_exclusive_group()
    kids.add_argument("--made-for-kids", dest="made_for_kids", action="store_const", const=True)
    kids.add_argument("--not-made-for-kids", dest="made_for_kids", action="store_const", const=False)
    p.add_argument("--delete", action="store_true", help="Delete the video (irreversible)")
    p.add_argument("--confirm-delete", metavar="VIDEO_ID", help="Repeat the video ID to confirm deletion")
    cli.add_safety_flags(p)
    cli.add_output_flags(p)
    args = p.parse_args()
    rt = cli.runtime()

    if args.delete:
        mode = decide_mode(dry_run=args.dry_run, confirm=args.confirm, action="DELETE a video")
        if mode != DRY_RUN and args.confirm_delete != args.video_id:
            raise ConfirmationRequired("Deletion is irreversible: pass --confirm-delete with the same video ID as --video-id.")
        client = cli.make_client(rt, ["videos.list", "videos.delete"])
        current = client.get_video(args.video_id, parts="snippet,status")
        if not current:
            raise ValidationError(f"Video {args.video_id} not found on this channel")
        target = {"video_id": args.video_id, "title": current["snippet"].get("title"), "privacy": current["status"].get("privacyStatus")}
        if mode == DRY_RUN:
            cli.emit({"mode": "dry_run", "would_call": ["videos.delete"], "target": target}, True)
            return 0
        client.delete_video(args.video_id)
        cli.emit({"mode": "execute", "deleted": target}, args.json, lambda d: f"Deleted {d['deleted']['video_id']} ({d['deleted']['title']})")
        return 0

    changes, r = changes_from_args(args)
    if not changes:
        p.error("nothing to update: pass --title/--description/--tags/--category/--privacy/--made-for-kids or --metadata")
    if not r.ok:
        raise ValidationError("Invalid update", r.errors)
    mode = decide_mode(dry_run=args.dry_run, confirm=args.confirm, action="update a video")
    client = cli.make_client(rt, ["videos.list", "videos.update"])
    current = client.get_video(args.video_id, parts="snippet,status")
    if not current:
        raise ValidationError(f"Video {args.video_id} not found on this channel")
    body, diff = merge_for_update(current, changes)
    parts = ",".join(sorted(changes))
    if mode == DRY_RUN:
        cli.emit({"mode": "dry_run", "would_call": ["videos.update"], "part": parts, "changes": diff, "request_body": body, "warnings": r.warnings}, True)
        return 0
    if not diff:
        cli.emit({"mode": "execute", "video_id": args.video_id, "changes": [], "note": "No changes; nothing sent."}, args.json, lambda d: d["note"])
        return 0
    updated = client.update_video(body, parts)
    cli.emit({"mode": "execute", "video_id": args.video_id, "changes": diff, "result": {k: updated.get(k) for k in ("snippet", "status")}}, args.json,
             lambda d: "Updated " + d["video_id"] + ":\n" + "\n".join(f"  {c['field']}: {c['old']!r} -> {c['new']!r}" for c in d["changes"]))
    return 0


if __name__ == "__main__":
    cli.run(main)
