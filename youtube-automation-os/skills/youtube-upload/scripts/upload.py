#!/usr/bin/env python3
"""Upload a video with the official YouTube Data API v3 (resumable upload).

Never uploads without --confirm. --dry-run validates everything and prints the exact
request body, planned API calls and quota estimate, making no write calls.

Examples:
  # Preview
  python skills/youtube-upload/scripts/upload.py --file data/videos/clip.mp4 \\
      --title "Judul video" --tags "nikah beda negara,indonesia pakistan" --privacy private --dry-run
  # Real private upload with generated metadata and a thumbnail
  python skills/youtube-upload/scripts/upload.py --file data/videos/clip.mp4 \\
      --metadata data/topics/out/metadata.json --thumbnail data/thumbnails/clip.jpg --confirm
  # Scheduled (publishAt requires private; it goes public at that time)
  python skills/youtube-upload/scripts/upload.py --file clip.mp4 --title "..." \\
      --privacy private --publish-at 2026-11-10T19:00:00+07:00 --confirm
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.config import get, load_yaml_file, upload_defaults  # noqa: E402
from src.exceptions import ValidationError  # noqa: E402
from src.safety import DRY_RUN, decide_mode  # noqa: E402
from src.state import make_job_id, sha256_file  # noqa: E402
from src.uploader import planned_calls, run_upload, spec_from_mapping, validate_spec, verify_video  # noqa: E402
from src.validators import validate_thumbnail  # noqa: E402

PARTIAL = 12


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", required=True, help="Video file to upload")
    p.add_argument("--metadata", help="YAML/JSON with title, description, tags, category_id (e.g. from generate_metadata.py)")
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--description-file")
    p.add_argument("--tags", help="Comma-separated tags")
    p.add_argument("--category", dest="category_id", help="Numeric category ID (default from settings / YOUTUBE_DEFAULT_CATEGORY)")
    p.add_argument("--privacy", choices=["private", "unlisted", "public"])
    kids = p.add_mutually_exclusive_group()
    kids.add_argument("--made-for-kids", dest="made_for_kids", action="store_const", const=True)
    kids.add_argument("--not-made-for-kids", dest="made_for_kids", action="store_const", const=False)
    p.add_argument("--publish-at", help="ISO-8601 with timezone, e.g. 2026-11-10T19:00:00+07:00 (requires --privacy private)")
    p.add_argument("--thumbnail", help="JPEG/PNG thumbnail to set after upload (validated first)")
    p.add_argument("--language", dest="default_language", help="defaultLanguage, e.g. id or en")
    p.add_argument("--no-notify", action="store_true", help="Do not notify subscribers")
    p.add_argument("--idempotency-key", help="Extra key mixed into the job ID (default: file hash only)")
    p.add_argument("--force-reupload", action="store_true", help="Upload even if this file was uploaded before")
    p.add_argument("--chunk-mb", type=int, help="Resumable chunk size in MB")
    p.add_argument("--no-verify", action="store_true", help="Skip post-upload verification (videos.list)")
    cli.add_safety_flags(p)
    cli.add_output_flags(p)
    return p


def collect(args: argparse.Namespace, defaults: dict) -> dict:
    m: dict = {}
    if args.metadata:
        m.update(load_yaml_file(args.metadata))
    for key in ("title", "description", "tags", "category_id", "privacy", "publish_at", "thumbnail", "default_language", "idempotency_key"):
        val = getattr(args, key, None)
        if val is not None:
            m[key] = val
    if args.description_file:
        m["description"] = Path(args.description_file).read_text(encoding="utf-8")
    if args.made_for_kids is not None:
        m["made_for_kids"] = args.made_for_kids
    if args.no_notify:
        m["notify_subscribers"] = False
    m["file"] = args.file
    return m


def main() -> int:
    args = build_parser().parse_args()
    rt = cli.runtime()
    defaults = upload_defaults(rt.settings)
    spec = spec_from_mapping(collect(args, defaults), defaults)
    verify = not args.no_verify and bool(get(rt.settings, "upload.verify_after_upload", True))

    result = validate_spec(spec, strict_thumbnail=bool(get(rt.settings, "thumbnail.strict", False)))
    if not result.ok:
        raise ValidationError("Upload input is invalid; nothing was sent", result.errors)

    mode = decide_mode(dry_run=args.dry_run, confirm=args.confirm, action="upload a video")
    calls = planned_calls(spec, verify=verify)
    file_sha = sha256_file(spec.file)
    previous = rt.store.find_upload(file_sha)
    quota_warnings = rt.quota.check(calls)
    if mode == DRY_RUN:
        cli.emit(
            {
                "mode": "dry_run",
                "would_call": calls,
                "request_body": spec.body(),
                "file": str(spec.file),
                "file_sha256": file_sha,
                "job_id": make_job_id(file_sha, spec.idempotency_key),
                "already_uploaded": previous,
                "quota_estimate": rt.quota.estimate(calls).by_bucket,
                "quota_remaining": rt.quota.report()["buckets"],
                "warnings": result.warnings + quota_warnings,
                "note": "Dry run: no API write calls were made.",
            },
            True,
        )
        return 0

    client = cli.make_client(rt, calls)
    chunk = (args.chunk_mb or int(get(rt.settings, "upload.chunk_size_mb", 8))) * 1024 * 1024

    def progress(done: int, total: int) -> None:
        print(f"  uploaded {done / total:6.1%} ({done}/{total} bytes)", file=sys.stderr)

    with rt.store.lock(make_job_id(file_sha, spec.idempotency_key)):
        job, video = run_upload(client, rt.store, spec, chunk_size=chunk, force_reupload=args.force_reupload, on_progress=progress)
        video_id = video["id"]
        out: dict = {"mode": "execute", "job_id": job["job_id"], "video_id": video_id, "url": f"https://youtu.be/{video_id}"}
        code = 0
        if spec.thumbnail:
            check = validate_thumbnail(spec.thumbnail)
            try:
                client.set_thumbnail(video_id, spec.thumbnail, check.info["mimetype"])
                rt.store.transition(job, "THUMBNAIL_SET", "thumbnail applied")
                out["thumbnail"] = "set"
            except Exception as exc:  # noqa: BLE001 - upload succeeded; report partial result honestly
                out["thumbnail"] = f"FAILED: {exc}"
                code = PARTIAL
        if verify:
            report = verify_video(client, video_id, spec)
            out["verification"] = report
            if report["ok"]:
                rt.store.transition(job, "VERIFIED", "remote settings match")
            else:
                code = code or PARTIAL
        rt.store.transition(job, "COMPLETED" if code == 0 else job["status"], "upload.py finished")
    cli.emit(out, args.json, lambda d: _human(d))
    return code


def _human(d: dict) -> str:
    lines = [f"Uploaded: {d['url']} (video {d['video_id']}, job {d['job_id']})"]
    if "thumbnail" in d:
        lines.append(f"Thumbnail: {d['thumbnail']}")
    v = d.get("verification")
    if v:
        lines.append(f"Verification: {'OK' if v['ok'] else 'MISMATCH'}")
        for c in v["checks"]:
            if not c["ok"]:
                lines.append(f"  {c['name']}: expected {c['expected']!r}, YouTube has {c['actual']!r}")
        for n in v["notes"]:
            lines.append(f"  note: {n}")
    return "\n".join(lines)


if __name__ == "__main__":
    cli.run(main)
