---
name: youtube-thumbnail
description: Validate YouTube thumbnail images (JPEG/PNG, ≤2 MB, width ≥640, 16:9, 1280x720 recommended) without modifying them, and set a validated thumbnail on a video with --confirm. Use for "generate a thumbnail validation report" or "set this thumbnail".
---

# youtube-thumbnail

## 1. Skill name
`youtube-thumbnail`

## 2. Description
Content-based image checks (Pillow) plus the official `thumbnails.set` upload.

## 3. Purpose
Catch thumbnails YouTube would reject, or display badly, before they cost quota.

## 4. When to use
- "Generate a thumbnail validation report" for one or many images.
- Before an upload or pipeline run (the pipeline runs this automatically).
- "Set this thumbnail on video X".

## 5. Required inputs
One or more image paths. For upload: exactly one image, `--upload --video-id ID`, plus `--confirm`.

## 6. Optional inputs
`--strict` (non-16:9 and non-1280x720 become errors), `--json`, `--dry-run`.

## 7. Expected outputs
Per image: `ok`, `errors`, `warnings`, and `info` (`format`, `width`, `height`, `bytes`, `aspect_ratio`, `mimetype`). Exit 0 if all images pass, 5 if any fails.

## 8. Dependencies
`Pillow`. Upload needs a token with the `upload` or `manage` scope. Custom thumbnails also require a **verified** YouTube channel (phone verification).

## 9. Exact execution commands
```bash
python skills/youtube-thumbnail/scripts/validate_thumbnail.py data/thumbnails/sample.jpg
python skills/youtube-thumbnail/scripts/validate_thumbnail.py data/thumbnails/*.jpg data/thumbnails/*.png --strict --json
python skills/youtube-thumbnail/scripts/validate_thumbnail.py data/thumbnails/a.jpg --upload --video-id VIDEO_ID --dry-run
python skills/youtube-thumbnail/scripts/validate_thumbnail.py data/thumbnails/a.jpg --upload --video-id VIDEO_ID --confirm
```

## 10. CLI arguments
`images...`, `--strict`, `--upload`, `--video-id`, `--dry-run`, `--confirm`, `--json`.

## 11. Configuration
`config/settings.yaml` → `thumbnail.strict`. The limits live in `src/validators.py` (`THUMB_MAX_BYTES = 2 MiB`, `THUMB_MIN_WIDTH = 640`, `THUMB_TARGET = 1280x720`, 1% aspect tolerance).

## 12. Error handling
| Check | Result |
|---|---|
| Missing, unreadable, truncated or corrupt file | error |
| Real format not JPEG/PNG (GIF, WEBP, text renamed .jpg…) | error |
| > 2 MB | error, with exact sizes |
| width < 640 | error |
| not 16:9 / not 1280x720 | warning (error with `--strict`) |
| extension disagrees with the real format | warning |
| `thumbnails.set` 403 | channel not verified for custom thumbnails, or the video is not yours |

## 13. Failure recovery
Validation never changes your image. Re-export it at 1280x720 JPEG with quality ≈ 85 (usually under 500 KB) and re-run. If the upload fails after a successful video upload, re-run only the `--upload … --confirm` command. The video is unaffected.

## 14. Security considerations
Read-only image inspection (`Image.verify()`), with no automatic resizing or recompression. Upload is a write and needs `--confirm`; quota cost is 50 units.

## 15. Integration with other skills
- `upload.py --thumbnail` and the pipeline's `thumbnail.file` run the same validator before uploading.
- Each records `THUMBNAIL_SET` in the job state.

## 16. Working examples
```text
$ python skills/youtube-thumbnail/scripts/validate_thumbnail.py data/thumbnails/sample.jpg small.jpg
PASS  data/thumbnails/sample.jpg  JPEG 1280x720 23 KB
FAIL  small.jpg  JPEG 320x180 1 KB
    ERROR: thumbnail: width 320px is below YouTube's minimum of 640px
    warning: thumbnail: 320x180; recommended size is 1280x720
```
