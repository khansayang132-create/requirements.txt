#!/usr/bin/env python3
"""List and download caption tracks through the official captions API.

Only works for videos the authenticated account owns or can edit: captions.download
returns 403 for other people's videos, and some tracks (e.g. auto-generated ones on
some videos) are not downloadable. Both cases are reported, not worked around.

Quota: captions.list = 50 units; captions.download is not on Google's current quota
page and is estimated at 200 units (configurable in settings.yaml).

Examples:
  python skills/youtube-transcript/scripts/download_captions.py --video-id ID --list
  python skills/youtube-transcript/scripts/download_captions.py --video-id ID --track TRACK_ID --format srt --out data/transcripts/ID.srt
  python skills/youtube-transcript/scripts/download_captions.py --video-id ID --language id --format vtt --out t.vtt
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.exceptions import APIError, ValidationError  # noqa: E402


def summarize(track: dict) -> dict:
    s = track.get("snippet", {})
    return {
        "id": track.get("id"),
        "language": s.get("language"),
        "name": s.get("name"),
        "trackKind": s.get("trackKind"),  # standard | asr (auto) | forced
        "isDraft": s.get("isDraft"),
        "status": s.get("status"),
        "lastUpdated": s.get("lastUpdated"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video-id", required=True)
    p.add_argument("--list", action="store_true", help="Only list caption tracks")
    p.add_argument("--track", help="Caption track ID to download")
    p.add_argument("--language", help="Pick the track with this language (if --track not given)")
    p.add_argument("--format", choices=["srt", "vtt", "sbv", "scc", "ttml"], default="srt")
    p.add_argument("--out", help="Output file (default: data/transcripts/<video>_<lang>.<format>)")
    cli.add_output_flags(p)
    args = p.parse_args()
    rt = cli.runtime()

    ops = ["captions.list"] if args.list else ["captions.list", "captions.download"]
    client = cli.make_client(rt, ops)
    tracks = [summarize(t) for t in client.list_captions(args.video_id)]
    if args.list or not tracks:
        cli.emit({"video_id": args.video_id, "tracks": tracks, "note": None if tracks else "No caption tracks on this video."}, args.json,
                 lambda d: "\n".join(f"{t['id']}  {t['language']}  {t['trackKind']}  {t['name']!r}  draft={t['isDraft']}" for t in d["tracks"]) or d["note"])
        return 0

    track_id = args.track
    if not track_id:
        matches = [t for t in tracks if not args.language or t["language"] == args.language]
        if not matches:
            raise ValidationError(f"No caption track with language '{args.language}'. Available: {', '.join(t['language'] or '?' for t in tracks)}")
        standard = [t for t in matches if t["trackKind"] != "asr"]
        track_id = (standard or matches)[0]["id"]
    chosen = next((t for t in tracks if t["id"] == track_id), {"id": track_id, "language": args.language or "xx"})

    try:
        data = client.download_caption(track_id, fmt=args.format)
    except APIError as exc:
        if exc.status == 403:
            raise APIError(
                "Caption download refused (403). captions.download only works for videos you own or are permitted to edit, "
                "and some tracks are not downloadable via the API.",
                status=403, reason=exc.reason, classification="permission",
            ) from exc
        raise
    out = Path(args.out) if args.out else ROOT / "data" / "transcripts" / f"{args.video_id}_{chosen.get('language') or 'xx'}.{args.format}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    cli.emit({"video_id": args.video_id, "track": chosen, "format": args.format, "file": str(out), "bytes": len(data)}, args.json,
             lambda d: f"Saved {d['bytes']} bytes to {d['file']}")
    return 0


if __name__ == "__main__":
    cli.run(main)
