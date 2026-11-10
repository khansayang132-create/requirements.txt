---
name: youtube-upload
description: Upload a video to YouTube (resumable, official Data API v3), schedule its publication, change its privacy or metadata, or delete it — always previewed with --dry-run and executed only with --confirm. Use for "upload this video privately", "schedule this video for tomorrow", "make it unlisted", "change the title".
---

# youtube-upload

## 1. Skill name
`youtube-upload`

## 2. Description
Single-video operations through the official YouTube Data API v3:
- `upload.py`: resumable upload, then thumbnail, then verification.
- `schedule.py`: compute or apply `publishAt`.
- `update_video.py`: metadata, privacy, made-for-kids, or delete.

## 3. Purpose
Publish one video safely. Each run is validated first and protected against duplicates. Interrupted uploads resume through their saved session. The result is checked against YouTube.

## 4. When to use
- "Upload this video privately" → `upload.py --privacy private`.
- "Schedule this video for tomorrow" → `schedule.py --tomorrow 19:00 --tz Asia/Jakarta`, then either `upload.py --publish-at …` or `schedule.py --video-id …`.
- "Make it unlisted / change the title" → `update_video.py`.
- For metadata generation, thumbnail checks and captions in one go, use **youtube-pipeline** instead.

## 5. Required inputs
- `upload.py`: `--file`, a title (`--title` or `--metadata`), and made-for-kids (default from settings: `false`).
- `schedule.py`: one of `--at` / `--tomorrow` / `--clear`; `--video-id` to apply it.
- `update_video.py`: `--video-id` plus at least one change, or `--delete`.

## 6. Optional inputs
`--description`/`--description-file`, `--tags a,b`, `--category ID`, `--privacy private|unlisted|public`, `--publish-at ISO8601+TZ`, `--thumbnail FILE`, `--language id`, `--no-notify`, `--idempotency-key`, `--force-reupload`, `--chunk-mb`, `--no-verify`.

## 7. Expected outputs
- Dry run: JSON with the exact request body, planned calls, quota estimate, file hash, job ID and duplicate status.
- Real run: video ID, `https://youtu.be/<id>`, thumbnail result, and a verification report (`uploadStatus`, title, category, privacy, publishAt, made-for-kids).

## 8. Dependencies
`google-api-python-client`, `google-auth*`, `Pillow` (thumbnail). Auth scopes: `upload,manage` (manage is needed for verification).

## 9. Exact execution commands
```bash
python skills/youtube-upload/scripts/upload.py --file data/videos/clip.mp4 --title "Judul" --privacy private --dry-run
python skills/youtube-upload/scripts/upload.py --file data/videos/clip.mp4 --metadata examples/sample_video.yaml --thumbnail data/thumbnails/clip.jpg --confirm
python skills/youtube-upload/scripts/schedule.py --tomorrow 19:00 --tz Asia/Jakarta
python skills/youtube-upload/scripts/upload.py --file clip.mp4 --title "Judul" --privacy private --publish-at 2026-11-10T19:00:00+07:00 --confirm
python skills/youtube-upload/scripts/schedule.py --video-id VIDEO_ID --at 2026-11-10T19:00:00+07:00 --confirm
python skills/youtube-upload/scripts/update_video.py --video-id VIDEO_ID --privacy unlisted --dry-run
python skills/youtube-upload/scripts/update_video.py --video-id VIDEO_ID --delete --confirm-delete VIDEO_ID --confirm
```

## 10. CLI arguments
Every script supports `--dry-run`, `--confirm` and `--json`. Run any script with `--help` for the full list. Extra arguments per script:
- `schedule.py`: `--allow-unpublish`.
- `update_video.py`: `--made-for-kids` / `--not-made-for-kids`, `--confirm-delete VIDEO_ID`.

## 11. Configuration
- `config/settings.yaml`: `defaults` (privacy, category, made_for_kids, language, notify_subscribers), `upload.chunk_size_mb`, `upload.verify_after_upload`.
- Env overrides: `YOUTUBE_DEFAULT_PRIVACY`, `YOUTUBE_DEFAULT_CATEGORY`.
- Safety lock: `YOUTUBE_DRY_RUN=true` refuses writes even with `--confirm`.

## 12. Error handling
| Exit | Meaning |
|---|---|
| 2 | No `--confirm` (or the env lock is on). Nothing was sent. |
| 4 | Auth or scope problem. Run youtube-auth. |
| 5 | Validation failed: title > 100 chars, `<`/`>`, description > 5000 bytes, tags > 500, `publishAt` without private, past time, missing file. |
| 6 | Quota exhausted. Stopped, no retries; resets at midnight Pacific. |
| 7 | This file was already uploaded (prints the existing video ID). |
| 8 | Upload uncertain. The session is saved; re-run the same command to resume. |
| 10 | API error after bounded retries (classified, with a hint). |
| 12 | Partial: the video uploaded, but the thumbnail or verification failed. |

## 13. Failure recovery
- Interrupted upload: re-run the exact same command. The saved resumable session is queried for its byte count before anything is sent, so the upload is never blindly started twice.
- Session expired: the channel's recent uploads are checked by title + file size. If that check is inconclusive the job becomes `NEEDS_MANUAL_CHECK`. Look in YouTube Studio, then run `state_manager.py resolve JOB --video-id ID`. Use `--force-reupload` only if the video is really missing.
- Partial (thumbnail failed): `python skills/youtube-thumbnail/scripts/validate_thumbnail.py thumb.jpg --upload --video-id ID --confirm`.

## 14. Security considerations
- Writes need `--confirm`. `--dry-run` always wins. Deleting also needs the video ID repeated.
- `update_video.py` sends every existing mutable field back, so a partial update never wipes the description or tags. `videos.update` replaces whole parts.
- Videos uploaded through an API project that has not passed Google's audit are locked to private. The verification report says so instead of claiming success.

## 15. Integration with other skills
- Metadata files come from **youtube-metadata** (`--metadata out.json`).
- Thumbnails are validated with **youtube-thumbnail** rules.
- The pipeline uses the same `src/uploader.py` core.
- Job state is shared with **youtube-pipeline** (`state_manager.py list`).

## 16. Working examples
```bash
$ python skills/youtube-upload/scripts/upload.py --file data/videos/sample.mp4 --title "Judul" --tags "a,b" \
    --privacy private --publish-at 2030-01-01T19:00:00+07:00 --dry-run
{ "mode": "dry_run", "would_call": ["videos.insert", "videos.list"],
  "request_body": {"snippet": {"title": "Judul", "description": "", "categoryId": "22", "tags": ["a","b"]},
                   "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": false, "publishAt": "2030-01-01T12:00:00Z"}},
  "quota_estimate": {"videos_insert": 1, "data_api": 1}, ... }
```
