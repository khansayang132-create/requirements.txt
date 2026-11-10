---
name: youtube-analytics
description: Retrieve channel or video performance from the official YouTube Analytics API — views, watch time, average view duration/percentage, subscribers gained/lost, engagement, traffic sources, audience retention — and render Markdown reports with period comparison. Unavailable metrics are reported as unavailable, never as zero. Use for "analyze my channel performance".
---

# youtube-analytics

## 1. Skill name
`youtube-analytics`

## 2. Description
`analytics.py` queries `youtubeAnalytics.reports.query` (v2) for `channel==MINE`. `reports.py` renders results as Markdown and compares two periods.

## 3. Purpose
Real numbers from YouTube with honest gaps. Nothing is estimated or invented.

## 4. When to use
- "Analyze my channel performance (last 28 days)" → `reports.py --live --days 28`.
- "How did video X do?" → `analytics.py --report overview --video-id X`.
- "Where do my views come from?" → `--report traffic`.
- "Where do viewers drop off?" → `--report retention --video-id X`.

## 5. Required inputs
A token with the `analytics` profile (`yt-analytics.readonly` + `youtube.readonly`).

## 6. Optional inputs
`--report overview|daily|traffic|retention|custom`, `--days N` or `--start/--end YYYY-MM-DD`, `--video-id`, `--metrics`, `--dimensions`, `--sort`, `--max-results`, `--out FILE.json`. For `reports.py`: `--input`, `--compare`, `--live`, `--out FILE.md`.

## 7. Expected outputs
JSON with `query`, `columns`, `rows`, `status` (`ok`/`no_data`) and per-metric `{value, status}`, where `status` is `ok`, `unavailable` (with a reason), `no_data` or `per_row`. `reports.py` produces a Markdown table with the previous value and the change.

## 8. Dependencies
`google-api-python-client` (`youtubeAnalytics` v2 discovery is bundled). Analytics quota is separate from the Data API and tracked in the `analytics` bucket.

## 9. Exact execution commands
```bash
python skills/youtube-analytics/scripts/analytics.py --report overview --days 28
python skills/youtube-analytics/scripts/analytics.py --report daily --start 2026-10-01 --end 2026-10-31 --out state/reports/oct.json
python skills/youtube-analytics/scripts/analytics.py --report traffic --days 28 --video-id VIDEO_ID
python skills/youtube-analytics/scripts/analytics.py --report retention --video-id VIDEO_ID --days 90
python skills/youtube-analytics/scripts/reports.py --live --days 28
python skills/youtube-analytics/scripts/reports.py --input state/reports/oct.json --compare state/reports/sep.json --out state/reports/oct.md
```

## 10. CLI arguments
See section 6. All scripts accept `--json`.

## 11. Configuration
Report definitions are in `REPORTS` in `analytics.py`. Overview metrics: `views`, `estimatedMinutesWatched`, `averageViewDuration`, `averageViewPercentage`, `subscribersGained`, `subscribersLost`, `likes`, `comments`, `shares`.

## 12. Error handling
| Case | Behaviour |
|---|---|
| **Impressions / impressions CTR** | Not exposed by the YouTube Analytics API (checked against the official metrics reference, updated 2026-09-14). Always shown as `unavailable` with a pointer to YouTube Studio → Analytics → Reach. Never 0. |
| Metric requested but not returned | `unavailable`, not 0 |
| No rows | `no_data` with a note: data usually lags 1-3 days |
| Retention without `--video-id` | Validation error: YouTube returns retention for a single video only |
| 403 insufficientPermissions | Classified `permission`; re-authenticate with `--scopes analytics --force` |

## 13. Failure recovery
Reads are idempotent and retried with backoff on 429/5xx. Re-run with a later `--end` if recent days show `no_data`.

## 14. Security considerations
Read-only scopes. Saved reports may contain business data, and `state/` is gitignored.

## 15. Integration with other skills
After a pipeline run, use the video ID from `state_manager.py list` with `--video-id`. Saved JSON feeds `reports.py`.

## 16. Working examples
```text
| Metric | Value | Previous | Change |
|---|---|---|---|
| Views | 150 | 100 | +50 (+50.0%) |
| Impressions | unavailable | unavailable | n/a |

**Unavailable metrics (not zero — the API does not provide them here):**
- Impressions: Thumbnail impressions are not exposed by the YouTube Analytics API; see YouTube Studio → Analytics → Reach.
```
