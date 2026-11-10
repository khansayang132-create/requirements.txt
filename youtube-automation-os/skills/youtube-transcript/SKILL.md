---
name: youtube-transcript
description: List, download and upload YouTube caption tracks through the official captions API (owner-only), validate and convert SRT/VTT files, and transcribe local media with optional Whisper when no captions exist. Use for "download my captions", "upload these subtitles", "make a transcript".
---

# youtube-transcript

## 1. Skill name
`youtube-transcript`

## 2. Description
- `download_captions.py`: `captions.list` + `captions.download`.
- `upload_captions.py`: local validation and conversion, then `captions.insert` / `captions.update`.
- `whisper_fallback.py`: optional local Whisper transcription.

## 3. Purpose
Get accurate captions onto your videos and get transcripts of your own videos, without scraping and without assuming every track is downloadable.

## 4. When to use
- "Upload these Indonesian subtitles to video X".
- "Download the captions of my video".
- No caption file exists → Whisper on the local video file, review the result, then upload.

## 5. Required inputs
- Download: `--video-id` (a video you own or can edit).
- Upload: `--file` (SRT/VTT) plus `--video-id` (new track) or `--update TRACK_ID`.
- Whisper: `--media` (a local file).

## 6. Optional inputs
`--language` (default `id`), `--name`, `--draft`, `--format srt|vtt|sbv|scc|ttml` (download), `--convert srt|vtt --out`, `--model tiny|base|small|medium|large`.

## 7. Expected outputs
- Track list (`id`, `language`, `trackKind` standard/asr/forced, `isDraft`, `status`).
- Downloaded file path.
- Upload result (track ID).
- Validation report (`cues`, `duration_s`, errors and warnings).
- Whisper SRT/VTT, labelled as machine transcription that needs review.

## 8. Dependencies
- Captions API: token with the `captions` profile (`youtube.force-ssl`).
- Whisper (optional): `pip install -r requirements-whisper.txt` (about 2 GB including PyTorch) plus the `ffmpeg` binary. Without them the script exits 9 and says what to install. Nothing is faked.

## 9. Exact execution commands
```bash
python skills/youtube-transcript/scripts/download_captions.py --video-id VIDEO_ID --list
python skills/youtube-transcript/scripts/download_captions.py --video-id VIDEO_ID --language id --format srt --out data/transcripts/VIDEO_ID.srt
python skills/youtube-transcript/scripts/upload_captions.py --file data/transcripts/sample.srt --validate-only
python skills/youtube-transcript/scripts/upload_captions.py --file data/transcripts/sample.srt --convert vtt --out data/transcripts/sample.vtt
python skills/youtube-transcript/scripts/upload_captions.py --video-id VIDEO_ID --file data/transcripts/sample.srt --language id --name "Bahasa Indonesia" --dry-run
python skills/youtube-transcript/scripts/upload_captions.py --video-id VIDEO_ID --file data/transcripts/sample.srt --language id --confirm
python skills/youtube-transcript/scripts/whisper_fallback.py --check
python skills/youtube-transcript/scripts/whisper_fallback.py --media data/videos/clip.mp4 --language id --out data/transcripts/clip.srt
```

## 10. CLI arguments
See section 6. Write commands also accept `--dry-run`, `--confirm` and `--json`.

## 11. Configuration
Quota costs in `config/settings.yaml`:
- `captions.list` 50, `captions.insert` 400, `captions.update` 450.
- `captions.download` 200, **unverified** (it is not on Google's current quota page, so the estimate prints a warning).

## 12. Error handling
| Case | Behaviour |
|---|---|
| Video not yours / track not downloadable | 403 is classified as `permission` and explained; never retried, never scraped |
| No tracks | Reported as "No caption tracks on this video" |
| Bad timing (end ≤ start), missing timing line, non-WEBVTT `.vtt` | Validation error (exit 5) before any upload |
| Overlapping cues, empty text | warnings |
| Whisper or ffmpeg missing | `DependencyMissing` (exit 9) with install command |

## 13. Failure recovery
A caption upload failure never affects the video. Re-run the upload command. In the pipeline, a caption failure marks step 11 as failed with exit code 12. Re-running the pipeline retries only the captions, because the video is already recorded.

## 14. Security considerations
- Only official endpoints, and only for videos the account owns or is allowed to edit.
- Whisper runs locally, so the media never leaves the machine and needs no API key.
- Review machine transcripts before publishing, especially names and religious terms.

## 15. Integration with other skills
The pipeline's `transcript:` section uses the same functions (`source: file|whisper`, `upload: true`). Captions are uploaded after the video, during step 11.

## 16. Working examples
```text
$ python skills/youtube-transcript/scripts/upload_captions.py --file data/transcripts/sample.srt --validate-only
Valid caption file: {'format': 'srt', 'cues': 2, 'duration_s': 3.0}
$ python skills/youtube-transcript/scripts/whisper_fallback.py --check
Whisper available: False (openai-whisper is not installed: pip install -r requirements-whisper.txt)
```
