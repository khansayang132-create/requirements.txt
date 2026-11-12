# First production test — status: BLOCKED

Requested: an original fictional presenter (realistic, professional clothing, neutral studio, ~10 s, clear speech,
lip sync, MP4).

| Part | Status | Evidence |
|---|---|---|
| Fictional character spec "Amara Lin" | PASS | `characters/amara-lin/character.json` (fictional, not based on a real person) |
| Pipeline end to end with the free mock provider | PASS | `rendered-videos/demo-presenter/final.mp4` 1080×1920, 10.10 s, h264/AAC 48 kHz, −14.0 LUFS, decodes cleanly |
| Real presenter video | **BLOCKED** | No `HEYGEN_API_KEY`, `SYNTHESIA_API_KEY`, `DID_API_KEY` or `ELEVENLABS_API_KEY`; provider hosts are also unreachable from this sandbox (proxy 403). No video was fabricated. |
| Spend | none | `spent_usd: 0.0`; no paid call was made |

Missing to run it for real (cheapest path: Synthesia `test: true` makes a free watermarked video):

1. `SYNTHESIA_API_KEY` (or `HEYGEN_API_KEY` + `heygen.avatar_id`/`voice_id`) in `.env`, on a machine that can reach the API.
2. `configuration/presenter.json` → `synthesia.avatar`.
3. `configuration/pricing.json` → a price (0 for Synthesia test videos).
4. `dhfactory init-job --script scripts/demo-presenter.txt --job demo-live --avatar synthesia --voice mock`
   then `dhfactory run --job demo-live --approve-spend`.
