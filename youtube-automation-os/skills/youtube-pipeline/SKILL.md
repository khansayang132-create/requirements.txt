---
name: youtube-pipeline
description: Run the complete YouTube publishing workflow from one YAML config — validate, auth check, metadata, thumbnail, transcript, quota estimate, state check, confirmed upload, assets, verification, report — with idempotency, duplicate protection, resumable recovery and state inspection. Use for "run the complete YouTube pipeline" and "show me yesterday's upload status".
---

# youtube-pipeline

## 1. Skill name
`youtube-pipeline`

## 2. Description
The central orchestrator (`pipeline.py`) plus three tools:
- `state_manager.py`: inspect and repair jobs, show quota.
- `verify_upload.py`: compare remote settings with what was requested.
- `retry_manager.py`: explain the error and retry policy, read failed calls from the log.

## 3. Purpose
Publish one video end to end, safely and repeatably. A config can be run any number of times: it uploads at most once.

## 4. When to use
- "Run the complete YouTube pipeline" → dry run first, then `--confirm`.
- "Show me yesterday's upload status" → `state_manager.py list --since 2d`.
- "Did my upload go through?" → `verify_upload.py --job-id …`.
- After a crash or timeout → re-run the same pipeline command.

## 5. Required inputs
`--config FILE` with `video.file` and either `metadata.topic_file` or `metadata.title`. See `examples/sample_pipeline.yaml`.

## 6. Optional inputs
Config sections:
- `publish`: privacy, publish_at, made_for_kids, notify_subscribers, default_language.
- `thumbnail`: file, strict.
- `transcript`: enabled, source file|whisper, file, language, name, upload, draft.
- `video.idempotency_key`.

CLI flags: `--dry-run`, `--confirm`, `--force-reupload`, `--json`.

## 7. Expected outputs
- Step table 1-14 with status `ok` / `skipped` / `dry_run` / `warning` / `failed` / `refused`.
- Job ID, job status, video ID and URL, the request body, planned calls, the quota report and warnings.
- A JSON report saved to `state/reports/<job>-<mode>-<UTC>.json`.

## 8. Dependencies
Everything in `requirements.txt`. Token profiles: `upload,manage`, plus `captions` if `transcript.upload`.

## 9. Exact execution commands
```bash
python skills/youtube-pipeline/scripts/pipeline.py --help
python skills/youtube-pipeline/scripts/pipeline.py --config examples/sample_pipeline.yaml --dry-run
python skills/youtube-pipeline/scripts/pipeline.py --config examples/sample_pipeline.yaml --confirm
python skills/youtube-pipeline/scripts/state_manager.py list --since 2d
python skills/youtube-pipeline/scripts/state_manager.py show JOB_ID
python skills/youtube-pipeline/scripts/state_manager.py quota
python skills/youtube-pipeline/scripts/state_manager.py resolve JOB_ID --video-id VIDEO_ID
python skills/youtube-pipeline/scripts/verify_upload.py --job-id JOB_ID
python skills/youtube-pipeline/scripts/retry_manager.py --status 403 --reason quotaExceeded
python skills/youtube-pipeline/scripts/retry_manager.py --from-log logs/ytaos.jsonl --last 20
```

## 10. CLI arguments
- `pipeline.py`: `--config`, `--dry-run`, `--confirm`, `--force-reupload`, `--json`.
- `state_manager.py`: subcommands `list [--since 24h|7d|YYYY-MM-DD] [--status S]`, `show`, `quota`, `resolve --video-id`, `unlock`, `reset --confirm [--forget-upload]`.
- `verify_upload.py`: `--job-id` | `--video-id`.
- `retry_manager.py`: `--status`, `--reason`, `--policy`, `--from-log`, `--last`.

## 11. Configuration
`config/settings.yaml`:
- `retry`: attempts, base and max delay.
- `upload`: chunk size, verify.
- `quota`: buckets and costs.
- `paths.state_dir`.

Env: `YOUTUBE_DRY_RUN` (safety lock), `YTAOS_STATE_DIR`, `YTAOS_LOG_PATH`, `LOG_LEVEL`.

Execution order:
1. validate_config
2. verify_auth (offline in dry run; credentials loaded and refreshed in a real run)
3. validate_video
4. generate_metadata
5. validate_thumbnail
6. process_transcript
7. estimate_quota
8. check_state
9. upload (only with `--confirm`)
10. verify_video_id
11. apply_assets (thumbnail, captions)
12. verify_publication
13. save_state
14. report

## 12. Error handling
Exit codes:

| Code | Meaning |
|---|---|
| 0 | ok |
| 2 | needs `--confirm` / safety lock |
| 3 | config |
| 4 | auth |
| 5 | validation |
| 6 | quota exhausted |
| 7 | duplicate upload |
| 8 | upload uncertain |
| 9 | optional dependency missing |
| 10 | API error |
| 11 | job locked |
| 12 | partial (video up, an asset or verification failed) |

The retry policy is in `src/retry.py`. 5xx and 429 errors get exponential backoff with full jitter, bounded. 401 errors trigger one refresh. Quota errors stop immediately.

## 13. Failure recovery
- **Interrupted / timeout:** the resumable session URI is saved as soon as Google issues it. Re-running asks Google how many bytes it has (`Content-Range: bytes */size`) and continues. A client-side timeout is never treated as "failed, upload again".
- **Session gone:** the channel's recent uploads are matched by title + file size. A match is adopted. If the check is inconclusive the job becomes `NEEDS_MANUAL_CHECK`. Check YouTube Studio, then run `state_manager.py resolve JOB --video-id ID` (or `--force-reupload` if it really is missing).
- **Partial (exit 12):** re-run the pipeline. Finished steps (`upload`, `thumbnail_set_for`, `captions_uploaded_for`) are skipped.
- **Stale lock after a kill:** `state_manager.py unlock JOB_ID`.

## 14. Security considerations
- Steps 1-8 are local and read-only. No upload happens without `--confirm`, and never while `YOUTUBE_DRY_RUN=true`. `--dry-run` overrides `--confirm`.
- Duplicate protection: the job ID comes from the file's SHA-256, and `state/uploads_index.json` refuses the same file under any config.
- Logs (`logs/ytaos.jsonl`) carry the timestamp, request ID, operation, endpoint, HTTP status, error class, retry count and result. Token-shaped strings are redacted.

## 15. Integration with other skills
Steps 4, 5, 6 and 9-12 reuse **youtube-metadata**, **youtube-thumbnail**, **youtube-transcript** and **youtube-upload** code (`src/`). Use **youtube-auth** first and **youtube-analytics** afterwards.

## 16. Working examples
```text
$ python skills/youtube-pipeline/scripts/pipeline.py --config examples/sample_pipeline.yaml --dry-run
Pipeline DRY_RUN  job=dc674de11828b0d9  status=PENDING
 ✓  1 validate_config      ok
 !  2 verify_auth          warning  not authenticated (NOT_AUTHENTICATED); run skills/youtube-auth/scripts/authenticate.py --scopes upload,manage,captions
 ✓  3 validate_video       ok       {"video_bytes": 18147}
 ✓  4 generate_metadata    ok       {"title": "Kalau kamu mau nikah beda negara… dengarkan ini dulu", ...}
 ✓  5 validate_thumbnail   ok       {"format": "JPEG", "width": 1280, "height": 720, "bytes": 23735}
 ✓  6 process_transcript   ok       {"format": "srt", "cues": 2, "duration_s": 3.0}
 ✓  7 estimate_quota       ok       {"calls": ["videos.insert", "thumbnails.set", "videos.list", "captions.insert"], "estimate": {"videos_insert": 1, "data_api": 451}}
 ✓  8 check_state          ok       {"job_id": "dc674de11828b0d9", "status": "PENDING", "video_id": null}
 ~  9 upload               dry_run  not executed (dry run)
 ...
 ✓ 14 report               ok       state/reports/dc674de11828b0d9-dry_run-….json
```
