# CLAUDE.md — YouTube Automation OS

You are operating a YouTube publishing toolkit. This file tells you which skill to use for a request and how to run it. Every skill is a set of Python CLIs over the shared library in `src/`. **Run commands from this folder** (`youtube-automation-os/`).

## Ground rules (never break these)

1. **Official Google APIs only:** YouTube Data API v3 and YouTube Analytics API v2 through `google-api-python-client`. No scraping, no unofficial endpoints, no quota workarounds.
2. **No write without `--confirm`.** Upload, update, delete, publish, schedule, privacy changes, thumbnail and caption writes all go through `src/safety.py`:
   - `--dry-run` wins over `--confirm`.
   - With neither flag the script refuses (exit 2).
   - `YOUTUBE_DRY_RUN=true` in `.env` refuses even with `--confirm`.
   - **Always run `--dry-run` first and show the user the request body before running with `--confirm`.** Ask before confirming anything public, a deletion, or a privacy change.
3. **Never print, log or commit secrets** (`.env`, `token.json`, client secrets). Scripts never print them; don't `cat` those files.
4. **Never claim success you didn't verify.** A video is "uploaded" only when a run returned a video ID. It is "published as requested" only when verification passed. Mocked tests prove nothing about the real channel.
5. **Report gaps as gaps.** An analytics metric the API doesn't return is "unavailable", never 0. An uncertain upload is "uncertain", never "failed, retrying".
6. **Content rules (LSKhan):** curiosity without lying, no invented events or statistics, the husband never looks stupid and the wife never cruel, and Islamic and family topics stay respectful. Metadata you draft must follow them.

## Setup (once)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # add -r requirements-dev.txt for tests
cp .env.example .env                       # fill GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET; keep YOUTUBE_DRY_RUN=true until ready
python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage,captions,analytics
```
The full Google Cloud setup is in `README.md` → "Google Cloud configuration".

## Skill discovery

The seven skills live in `skills/<name>/SKILL.md` (with YAML frontmatter). They are also linked into `.claude/skills/` in this folder. Claude Code discovers them as folder-scoped skills when you work here. These are **not** custom slash commands. If a skill isn't listed in your session, read its `SKILL.md` directly and run the documented script.

| User says | Skill | Command (run `--dry-run` first where it applies) |
|---|---|---|
| "Authenticate my YouTube account" | youtube-auth | `python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage` |
| "Is my YouTube connected?" | youtube-auth | `python skills/youtube-auth/scripts/validate_auth.py --require upload,manage --live` |
| "Upload this video privately" | youtube-upload | `python skills/youtube-upload/scripts/upload.py --file F --title "…" --privacy private --dry-run` → then `--confirm` |
| "Schedule this video for tomorrow" | youtube-upload | `python skills/youtube-upload/scripts/schedule.py --tomorrow 19:00 --tz Asia/Jakarta`, then `upload.py … --privacy private --publish-at <time>` or `schedule.py --video-id ID --at <time> --confirm` |
| "Change the title / make it unlisted" | youtube-upload | `python skills/youtube-upload/scripts/update_video.py --video-id ID --title "…" --dry-run` |
| "Generate SEO metadata" | youtube-metadata | Write `data/topics/<slug>.yaml` (hook, summary, points, keywords, CTA), then `python skills/youtube-metadata/scripts/generate_metadata.py --topic data/topics/<slug>.yaml --out data/topics/out/<slug>.json` |
| "Generate a thumbnail validation report" | youtube-thumbnail | `python skills/youtube-thumbnail/scripts/validate_thumbnail.py data/thumbnails/*.jpg` |
| "Upload these subtitles" / "transcribe" | youtube-transcript | `upload_captions.py --video-id ID --file F.srt --language id --dry-run`; `whisper_fallback.py --check` |
| "Analyze my channel performance" | youtube-analytics | `python skills/youtube-analytics/scripts/reports.py --live --days 28` |
| "Run the complete YouTube pipeline" | youtube-pipeline | `python skills/youtube-pipeline/scripts/pipeline.py --config <cfg>.yaml --dry-run` → then `--confirm` |
| "Show me yesterday's upload status" | youtube-pipeline | `python skills/youtube-pipeline/scripts/state_manager.py list --since 2d` |
| "Did it really upload?" | youtube-pipeline | `python skills/youtube-pipeline/scripts/verify_upload.py --job-id JOB` |
| "How much quota is left?" | youtube-pipeline | `python skills/youtube-pipeline/scripts/state_manager.py quota` |

## Workflows

**Authentication.**
1. Run `validate_auth.py`. On exit 4, run `authenticate.py` with the profiles the task needs: `upload,manage` for uploading, `+captions` for subtitles, `+analytics` for reports.
2. The consent URL must be opened on the same device (loopback redirect). On a headless machine use `--no-browser` and open the printed URL in that device's browser.

**Upload.**
1. Validate inputs.
2. Run `--dry-run` and show the user the body and quota estimate.
3. Run `--confirm`.
4. Report the video URL and the verification result.
If verification says privacy is `private` although `public` was requested, the API project hasn't passed Google's audit. Say so and don't retry.

**Thumbnail.**
1. Validate.
2. If it fails, tell the user exactly what to change. The toolkit never edits images.
3. Upload with `--upload --video-id ID --confirm`.

**Transcript.**
1. Prefer a human-made SRT/VTT.
2. Otherwise run `whisper_fallback.py` on the local file. It needs `requirements-whisper.txt` and ffmpeg; exit 9 means they aren't installed.
3. Ask the user to review the machine transcript.
4. Upload it.

**Analytics.**
1. Run `reports.py --live --days 28`, or `analytics.py --report traffic|retention --video-id ID`.
2. Quote numbers exactly.
3. Impressions and CTR are not in the API: point to YouTube Studio → Reach.

**Pipeline.**
1. Copy `examples/sample_pipeline.yaml` and edit it.
2. Run `--dry-run` and read all 14 steps and the warnings.
3. Run `--confirm`.
4. On exit 12, re-run the same command; finished steps are skipped.

## Recovery procedures

| Exit / state | Do this |
|---|---|
| 2 | Expected safety stop. Show the dry run and ask for confirmation. |
| 4 | Run youtube-auth with the missing scopes. |
| 5 | Fix the listed validation errors; nothing was sent. |
| 6 | Quota exhausted. Stop for today (resets at midnight Pacific). Don't retry; `state_manager.py quota` shows the ledger. |
| 7 | The file was already uploaded; give the user the existing video ID. Only use `--force-reupload` if they explicitly want a second copy. |
| 8 / `UPLOAD_UNCERTAIN` | Re-run the same command. It resumes the saved session after asking Google for the byte count. |
| `NEEDS_MANUAL_CHECK` | Ask the user to check YouTube Studio → Content. If the video is there, run `state_manager.py resolve JOB --video-id ID`. If it isn't, re-run with `--force-reupload`. |
| 11 | Another run holds the lock. If none is running: `state_manager.py unlock JOB`. |
| 12 | Partial: the video is up. Re-run to retry the thumbnail, captions or verification only. |

To diagnose failures: run `retry_manager.py --from-log logs/ytaos.jsonl` (no secrets in it) and quote the `request_id` to the user.

## Code map

| Path | What |
|---|---|
| `src/youtube_client.py` | All API calls (quota + retry + logging); resumable upload with session resume |
| `src/oauth_manager.py` | OAuth flow, token storage (0600), refresh, scope checks, redacted status |
| `src/quota_manager.py` | Bucket-aware quota ledger (Pacific day), exhaustion lock |
| `src/retry.py` | Error classification and bounded backoff with jitter |
| `src/uploader.py` | Shared upload/verify/merge-update logic, duplicate protection |
| `src/state.py` | Job state, idempotency, upload index, locks |
| `src/validators.py` / `metadata.py` / `captions.py` | Limits, generation, SRT/VTT + Whisper |
| `src/safety.py` | The confirmation gate |
| `config/settings.yaml`, `config/scopes.yaml` | Defaults, verified quota costs, templates, scopes |
| `STATUS.md` | What is VERIFIED vs IMPLEMENTED vs BLOCKED. Update it when that changes. |

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest -q        # mocked HTTP through the real Google client library; no network
ruff check .
```
A change to any API path needs a test in `tests/` using `ScriptedHttp` (see `tests/conftest.py`).
