# STATUS — YouTube Automation OS

Same convention as `apex/STATUS.md`: **VERIFIED** (a test or run proved it here) · **IMPLEMENTED** (code exists, not proven against the real service) · **BLOCKED** (cannot be checked from the build sandbox) · **NOT IMPLEMENTED**.

Build date: 2026-11-09. Python 3.13.18. All results below come from runs in this repository.

## Verification levels completed

| Level | Result |
|---|---|
| 1 Static | `ruff check .` clean; `python -m compileall src skills tests` OK |
| 2 Unit | part of the 168-test pytest suite, run on Python 3.13.18 and 3.11.18 (validators, retry, quota, state, redaction, captions, metadata) |
| 3 Integration | in the same suite: the real `google-api-python-client` + `google-auth` with scripted HTTP (resumable protocol, multipart media, OAuth token refresh, analytics) and subprocess runs of the CLIs |
| 4 Real Google API | **BLOCKED**: no Google Cloud credentials in the build environment, and its network policy denies `developers.google.com` (and Google APIs were not attempted). Nothing was uploaded to YouTube. |

## Capabilities

| Capability | Status | Evidence |
|---|---|---|
| OAuth client config from env / secrets file | VERIFIED (L2) | `test_auth.py` |
| Token storage 0600, atomic, no secrets in status/logs | VERIFIED (L2) | `test_status_reports_state_but_never_secret_values`, `test_redaction_masks_tokens_everywhere` |
| Token refresh incl. revoked refresh token | VERIFIED (L3, fake token endpoint) | `test_expired_token_is_refreshed_and_saved_privately`, `test_revoked_refresh_token_…` |
| Installed-app consent flow (`run_local_server`) | IMPLEMENTED | Parameters tested with a fake flow; the real browser consent is BLOCKED (needs credentials) |
| Resumable upload, request body, publishAt in UTC | VERIFIED (L3) | `test_full_run_uploads_once_and_completes`, `test_scheduled_publish_sends_utc_publish_at` |
| Resume after timeout through the saved session (no second upload) | VERIFIED (L3) | `test_interrupted_upload_resumes_from_saved_session` |
| Lost session → remote check by title + size → adopt or NEEDS_MANUAL_CHECK | VERIFIED (L3) | `test_expired_session_…`, `test_inconclusive_remote_check_needs_a_human` |
| Duplicate prevention / idempotent re-run | VERIFIED (L3) | `test_same_file_under_another_job_is_refused`, `test_rerun_is_idempotent` |
| Dry run makes no API calls; `--dry-run` beats `--confirm`; refusal without flags; env lock | VERIFIED (L2/L3) | `test_dry_run_…`, `test_confirmation_rules`, CLI subprocess tests |
| Quota: bucket-aware estimate, ledger, Pacific reset, 403 lock without retry | VERIFIED (L2/L3) | `test_quota.py` |
| Quota costs match Google's page | VERIFIED 2026-11-09 against the page (updated 2026-11-03) | `test_costs_match_verified_google_table`; `captions.download` marked unverified (not on the page) |
| Retry: classification, full-jitter backoff, bounds, Retry-After, 401 refresh, no network retry for non-idempotent calls | VERIFIED (L2) | `test_retry.py` |
| Structured logs with request IDs; redaction | VERIFIED (L2/L3) | `test_client_call_retries_then_succeeds_and_logs` |
| Metadata generation + limits (100 chars, 5000 bytes, 500-char tags, duplicates, `<>`) | VERIFIED (L2) | `test_metadata.py` |
| Thumbnail validation (format by content, 2 MB, 640 min width, 16:9, corruption, never modified) | VERIFIED (L2) | `test_thumbnail.py` |
| thumbnails.set request | VERIFIED (L3) | `test_set_thumbnail_sends_media_to_official_endpoint` |
| SRT/VTT parse, validate, convert | VERIFIED (L2) | `test_transcript_analytics.py` |
| captions.list / download / insert requests; 403 not retried | VERIFIED (L3) | `test_caption_api_calls`, `test_caption_download_forbidden_is_not_retried` |
| Whisper fallback | IMPLEMENTED; missing-dependency path VERIFIED | `openai-whisper` (~2 GB) not installed in the sandbox, so a real transcription is not verified |
| Analytics queries, unavailable ≠ 0, no_data, retention needs video | VERIFIED (L3, mocked responses) | `test_overview_query_and_unavailable_metrics`, `test_zero_is_not_unavailable_…` |
| Impressions / CTR | NOT AVAILABLE IN API | Checked against the official metrics reference (updated 2026-09-14); reported as unavailable |
| videos.update merge (nothing silently cleared) | VERIFIED (L2) | `test_merge_keeps_existing_fields` |
| Delete (`--confirm` + repeated ID) | VERIFIED gate (L2); remote delete IMPLEMENTED | `test_delete_requires_repeating_the_id` |
| Schedule computation and rules | VERIFIED (L2) | `test_schedule_tomorrow_computation`, `test_schedule_cli_rejects_past_time` |
| Claude Code skill discovery via `.claude/skills/` links | IMPLEMENTED | Frontmatter checked by `test_skills_docs.py`; folder-scoped discovery depends on the Claude Code version and was not observed in a fresh session |

## Remaining manual steps (owner)

1. Create the Google Cloud project, enable both APIs, configure the consent screen and create a **Desktop app** OAuth client (README → Google Cloud configuration).
2. Fill `.env`, run `authenticate.py --scopes upload,manage,captions,analytics`, then `validate_auth.py --live`.
3. Run the pipeline with `--dry-run` on a real video, set `YOUTUBE_DRY_RUN=false`, then run `--confirm` with `privacy: private`.
4. Run `verify_upload.py --job-id …` and look at the video in YouTube Studio. That is the first **LEVEL 4** verification; record it here.
5. For public uploads through the API, request Google's YouTube API audit.
