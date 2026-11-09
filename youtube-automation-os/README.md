# YouTube Automation OS

A self-contained toolkit that lets Claude (or you) run the YouTube publishing lifecycle through **official Google APIs only**:
- authenticate
- generate and validate metadata
- validate thumbnails
- manage captions and transcripts
- upload with resumable sessions
- schedule, update or delete
- verify, read analytics

Every write is gated behind `--confirm`. Every API call is quota-tracked, retried within limits, and logged without secrets.

> **Verification status:** see [STATUS.md](STATUS.md). Short version: everything is unit- and integration-tested against the real Google client library with mocked HTTP. **No real YouTube upload has been performed from this build**: that needs your Google Cloud credentials.

---

## Contents
1. [Architecture](#architecture)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Google Cloud configuration](#google-cloud-configuration) (OAuth setup, API enablement, credentials)
5. [Authentication](#authentication)
6. [Dry run](#dry-run-example) · [Real upload](#real-upload-example) · [Scheduling](#scheduling)
7. [Thumbnail validation](#thumbnail-validation) · [Transcript processing](#transcript-processing) · [Analytics](#analytics)
8. [Pipeline usage](#pipeline-usage)
9. [Quota considerations](#quota-considerations)
10. [Reliability](#reliability) · [Troubleshooting](#troubleshooting) · [Security](#security) · [Testing](#testing)

---

## Architecture

```
youtube-automation-os/
├── CLAUDE.md                 how Claude picks and runs skills
├── README.md  STATUS.md      docs / what is verified
├── requirements.txt          runtime (pinned)   requirements-dev.txt (pytest, ruff)   requirements-whisper.txt (optional)
├── .env.example  .gitignore
├── config/
│   ├── settings.yaml         defaults, retry policy, VERIFIED quota costs, metadata templates
│   └── scopes.yaml           OAuth scope profiles + scopes accepted per operation
├── skills/                   7 skills, each SKILL.md (frontmatter) + scripts/ (CLIs)
│   ├── youtube-auth/         authenticate.py  refresh_token.py  validate_auth.py
│   ├── youtube-upload/       upload.py  schedule.py  update_video.py
│   ├── youtube-analytics/    analytics.py  reports.py
│   ├── youtube-metadata/     generate_metadata.py
│   ├── youtube-thumbnail/    validate_thumbnail.py
│   ├── youtube-transcript/   download_captions.py  upload_captions.py  whisper_fallback.py
│   └── youtube-pipeline/     pipeline.py  state_manager.py  retry_manager.py  verify_upload.py
├── src/                      shared library (all API traffic goes through youtube_client.py)
│   ├── youtube_client.py  oauth_manager.py  quota_manager.py  logger.py  validators.py  exceptions.py
│   └── retry.py  state.py  uploader.py  safety.py  metadata.py  captions.py  config.py  cli.py
├── data/{topics,videos,thumbnails,transcripts}/   inputs (small samples included)
├── state/                    job state, quota ledger, duplicate index, reports (gitignored)
├── logs/                     ytaos.jsonl structured logs (gitignored)
├── tests/                    pytest suite (no network)
└── examples/                 sample_video.yaml  sample_pipeline.yaml
```

```
CLI script ──► src/safety (gate) ──► src/validators ──► src/youtube_client.call()
                                                         ├─ quota_manager.check / record / mark_exhausted
                                                         ├─ retry.RetryPolicy (classify, backoff+jitter, refresh on 401)
                                                         ├─ logger (request_id, endpoint, status, class, retries; redacted)
                                                         └─ googleapiclient (static discovery docs) ──► Google
```

`.claude/skills/` in this folder links to each `skills/<name>` so Claude Code can discover them as folder-scoped skills.

## Requirements

- Python **3.11+** (developed and tested on 3.13).
- A Google account with a YouTube channel. Custom thumbnails need a **verified** channel (phone verification).
- A Google Cloud project (free) with the two YouTube APIs enabled.
- Optional: `ffmpeg` and `requirements-whisper.txt` for local transcription.

## Installation

```bash
cd youtube-automation-os
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # tests + lint (optional)
cp .env.example .env
```

## Google Cloud configuration

1. **Create a project:** https://console.cloud.google.com/projectcreate
2. **Enable the APIs** (APIs & Services → Library):
   - *YouTube Data API v3*
   - *YouTube Analytics API* (only for analytics)
3. **OAuth consent screen** (Google Auth Platform → Branding / Audience):
   - User type *External*.
   - Add your Google account as a **test user** while the app is in *Testing*.
   - In *Testing*, refresh tokens expire after **7 days**. Publish the app (Audience → Publish) to avoid weekly re-authentication.
4. **Create credentials** (Clients → Create client): type **Desktop app**. Copy the client ID and secret into `.env`:
   ```
   GOOGLE_CLIENT_ID=…apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=…
   ```
   Or download the JSON and set `GOOGLE_CLIENT_SECRETS_FILE=credentials.json`. It is gitignored.
5. **Public uploads need an audit.** Videos uploaded through an API project that has not completed the YouTube API compliance audit are locked to **private**. That applies to projects created after 28 July 2020. Request the audit from the YouTube API Services form if you need public uploads. The toolkit's verification step detects and explains this.
6. **Quota:** the default is 10,000 units/day plus 100 `videos.insert` calls/day (see [Quota](#quota-considerations)). You can request more in the Cloud Console.

Official docs: https://developers.google.com/youtube/v3 · https://developers.google.com/youtube/analytics · https://developers.google.com/identity/protocols/oauth2

## Authentication

```bash
python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage
# + captions and analytics:
python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage,captions,analytics --force
python skills/youtube-auth/scripts/validate_auth.py --require upload,manage --live
```
A browser opens the Google consent page and redirects to `http://localhost:8080/`. The token is saved to `token.json` with mode 600. It is never printed. Use `--no-browser` to print the URL instead, and open it **on the same device**.

## Dry run example

```bash
python skills/youtube-pipeline/scripts/pipeline.py --help
python skills/youtube-pipeline/scripts/pipeline.py \
  --config examples/sample_pipeline.yaml \
  --dry-run
```
This validates the config, video, metadata (generated from `data/topics/sample_topic.yaml`), thumbnail and captions. It checks auth offline, estimates quota and records the job. It prints the exact request body and makes **no API calls**.

## Real upload example

```bash
# 1. set YOUTUBE_DRY_RUN=false in .env (the safety lock)
# 2. point examples/sample_pipeline.yaml (or a copy) at your own video
python skills/youtube-pipeline/scripts/pipeline.py \
  --config examples/sample_pipeline.yaml \
  --confirm
```
Single file without the pipeline:
```bash
python skills/youtube-upload/scripts/upload.py --file data/videos/clip.mp4 \
  --title "Judul video" --tags "nikah beda negara,indonesia pakistan" --privacy private --dry-run
python skills/youtube-upload/scripts/upload.py --file data/videos/clip.mp4 \
  --title "Judul video" --tags "nikah beda negara,indonesia pakistan" --privacy private --confirm
```

## Scheduling

YouTube publishes a scheduled video only when it is uploaded or updated as **private** with `status.publishAt`. The toolkit enforces this rule.
```bash
python skills/youtube-upload/scripts/schedule.py --tomorrow 19:00 --tz Asia/Jakarta     # prints the time + flag
python skills/youtube-upload/scripts/upload.py --file clip.mp4 --title "…" --privacy private \
  --publish-at 2026-11-10T19:00:00+07:00 --confirm
python skills/youtube-upload/scripts/schedule.py --video-id VIDEO_ID --at 2026-11-10T19:00:00+07:00 --confirm
python skills/youtube-upload/scripts/schedule.py --video-id VIDEO_ID --clear --confirm
```

## Thumbnail validation

```bash
python skills/youtube-thumbnail/scripts/validate_thumbnail.py data/thumbnails/*.jpg
python skills/youtube-thumbnail/scripts/validate_thumbnail.py thumb.jpg --upload --video-id VIDEO_ID --confirm
```
Checks:
- JPEG/PNG (by content).
- ≤ 2 MB.
- Width ≥ 640.
- 16:9 and 1280×720 are recommended; `--strict` makes them required.
- The file is not corrupt.

Images are never modified.

## Transcript processing

```bash
python skills/youtube-transcript/scripts/upload_captions.py --file subs.srt --validate-only
python skills/youtube-transcript/scripts/upload_captions.py --file subs.srt --convert vtt --out subs.vtt
python skills/youtube-transcript/scripts/upload_captions.py --video-id VIDEO_ID --file subs.srt --language id --confirm
python skills/youtube-transcript/scripts/download_captions.py --video-id VIDEO_ID --list
pip install -r requirements-whisper.txt      # optional, large
python skills/youtube-transcript/scripts/whisper_fallback.py --media clip.mp4 --language id --out subs.srt
```
`captions.download` only works for videos you own or can edit. Other cases return 403, which is reported, not worked around.

## Analytics

```bash
python skills/youtube-analytics/scripts/reports.py --live --days 28
python skills/youtube-analytics/scripts/analytics.py --report traffic --days 28
python skills/youtube-analytics/scripts/analytics.py --report retention --video-id VIDEO_ID --days 90
```
Reported metrics:
- views, estimated watch time, average view duration and percentage
- subscribers gained and lost
- likes, comments, shares
- traffic sources
- audience retention

**Impressions and impressions CTR are not available from the YouTube Analytics API.** They are shown as *unavailable* (never 0); see YouTube Studio → Reach. Recent days may show *no data* because processing usually takes 1-3 days.

## Pipeline usage

Steps:
1. validate config
2. verify auth
3. validate video
4. generate metadata
5. validate thumbnail
6. process transcript
7. estimate quota
8. check state
9. **upload (only with `--confirm`)**
10. verify video ID
11. apply thumbnail + captions
12. verify publication settings
13. save state
14. report (`state/reports/*.json`)

Re-running the same config is safe: finished steps are skipped. An interrupted upload is resumed. The same file is never uploaded twice. Useful companions:
```bash
python skills/youtube-pipeline/scripts/state_manager.py list --since 2d     # "yesterday's upload status"
python skills/youtube-pipeline/scripts/verify_upload.py --job-id JOB_ID
python skills/youtube-pipeline/scripts/state_manager.py quota
```

## Quota considerations

These costs were checked against Google's [quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost) on 2026-11-09 (page last updated 2026-11-03). They are configurable in `config/settings.yaml`.

| Operation | Cost | Bucket |
|---|---|---|
| `videos.insert` | **1 per call** | own bucket: **100 calls/day** |
| `search.list` | 1 per call | own bucket: 100 calls/day (not used) |
| `videos.list`, `channels.list`, `playlistItems.list` | 1 | 10,000 units/day |
| `videos.update` / `videos.delete` | 50 / 50 | 10,000 units/day |
| `thumbnails.set` | 50 | 10,000 units/day |
| `captions.list` / `insert` / `update` / `delete` | 50 / 400 / 450 / 50 | 10,000 units/day |
| `captions.download` | ~200 (**not on Google's current page; unverified estimate**) | 10,000 units/day |
| Analytics `reports.query` | tracked per query | separate Analytics API quota |

Older material quotes ~1,600 units per upload. That figure **no longer applies**, which is why costs are configuration rather than hardcoded.
- A full pipeline run with thumbnail and captions costs 1 `videos.insert` call plus about 451 units.
- The ledger (`state/quota_ledger.json`) is an estimate keyed to the Pacific-time day.
- A `403 quotaExceeded` locks that bucket for the rest of the day instead of retrying.
- Override the daily unit budget with `YOUTUBE_DAILY_QUOTA`.

## Reliability

| Condition | Behaviour |
|---|---|
| 401 | Refresh the token once, retry once |
| 403 quotaExceeded / dailyLimitExceeded / uploadLimitExceeded | Stop, mark the bucket exhausted, no retries |
| 403 insufficientPermissions / forbidden | Fail with a scope/ownership hint |
| 404 | Report the missing resource |
| 429, 403 rateLimitExceeded | Backoff (honours `Retry-After`) |
| 500/502/503/504, network timeouts | Exponential backoff with full jitter, max 5 attempts, cap 64 s |
| Upload timeout | **Never "upload again"**. Query the saved resumable session for the byte count and continue. If the session is gone, match the channel's recent uploads (title + file size). If still unsure: `NEEDS_MANUAL_CHECK`. |

Every log record (`logs/ytaos.jsonl`) holds: timestamp, request ID, operation, endpoint, HTTP status, error class, retry count, result.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ConfigError: Missing OAuth client configuration` | Fill `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env` |
| `redirect_uri_mismatch` in the browser | The client must be a **Desktop app**; keep `GOOGLE_REDIRECT_URI` on localhost |
| `access_denied` / "app not verified" | Add your account as a test user on the consent screen |
| `Token refresh failed … invalid_grant` | Refresh token expired (Testing apps: 7 days) or was revoked: `authenticate.py --force` |
| `ScopeError` | `authenticate.py --scopes upload,manage,captions,analytics --force` |
| Exit 2 with `--confirm` | `YOUTUBE_DRY_RUN=true` in `.env`; set it to `false` |
| Uploaded video stays private | The API project hasn't passed the YouTube audit (see Google Cloud step 5) |
| `thumbnails.set` 403 | Verify the channel at https://www.youtube.com/verify |
| Exit 6 | Daily quota is used up; wait for midnight Pacific or request more quota |
| Exit 8 / `NEEDS_MANUAL_CHECK` | See CLAUDE.md → Recovery procedures |

## Security

- Credentials only in `.env` / `token.json` (both gitignored). The token file is mode 0600 and written atomically.
- Nothing prints tokens. Logs pass through `src/logger.redact`, which masks secret-named keys plus `ya29.`, `1//`, `GOCSPX-`, `AIza` and bearer patterns.
- Writes need `--confirm`; `--dry-run` overrides it; `YOUTUBE_DRY_RUN=true` blocks all writes. Deleting needs the video ID typed twice.
- Updates merge existing fields so nothing is silently cleared.
- Request the fewest OAuth scopes needed; revoke at https://myaccount.google.com/permissions.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
```
The suite drives the real `google-api-python-client` (bundled discovery documents) against scripted HTTP responses. It covers:
- resumable upload, including resume after a timeout and recovery after a lost session
- quota exhaustion, retries and backoff
- dry-run and confirmation rules
- idempotency and duplicate protection
- OAuth refresh through `google-auth`
- analytics honesty
- logging redaction

It makes **no network calls** and proves nothing about your real channel: see [STATUS.md](STATUS.md).
