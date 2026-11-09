#!/usr/bin/env python3
"""Verify a video on YouTube against what the pipeline asked for (read-only: videos.list, 1 unit).

Checks uploadStatus (uploaded/processed, not rejected/failed), title, category, privacy,
publishAt and made-for-kids. Explains the common "uploaded as private although public
was requested" case (unverified API project).

Examples:
  python skills/youtube-pipeline/scripts/verify_upload.py --job-id 3f2a9c1d0b7e4a55
  python skills/youtube-pipeline/scripts/verify_upload.py --video-id VIDEO_ID
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.config import upload_defaults  # noqa: E402
from src.exceptions import ValidationError  # noqa: E402
from src.uploader import spec_from_mapping, verify_video  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", help="Verify the video recorded in this job, against the job's requested settings")
    g.add_argument("--video-id", help="Just report this video's remote state")
    cli.add_output_flags(p)
    args = p.parse_args()
    rt = cli.runtime()

    spec = None
    video_id = args.video_id
    job = None
    if args.job_id:
        job = rt.store.load(args.job_id)
        if not job:
            raise ValidationError(f"No job {args.job_id}")
        video_id = job.get("video_id")
        if not video_id:
            raise ValidationError(f"Job {args.job_id} has no video yet (status {job['status']})")
        if job.get("spec"):
            spec = spec_from_mapping({**job["spec"], "thumbnail": None}, upload_defaults(rt.settings))

    client = cli.make_client(rt, ["videos.list"])
    report = verify_video(client, video_id, spec)
    if job and report["ok"] and job["status"] in ("UPLOADED", "THUMBNAIL_SET"):
        rt.store.transition(job, "VERIFIED", "verify_upload.py")
    cli.emit(report, args.json, _human)
    return 0 if report["ok"] else 12


def _human(r: dict) -> str:
    if not r["exists"]:
        return f"Video {r['video_id']}: NOT FOUND. " + " ".join(r["notes"])
    lines = [f"Video {r['video_id']} ({r['url']}): {'OK' if r['ok'] else 'MISMATCH'}"]
    for c in r["checks"]:
        lines.append(f"  {'✓' if c['ok'] else '✗'} {c['name']}: expected {c['expected']!r}, YouTube has {c['actual']!r}")
    lines += [f"  note: {n}" for n in r["notes"]]
    return "\n".join(lines)


if __name__ == "__main__":
    cli.run(main)
