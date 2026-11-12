# Wonderland Studio

An automated studio for an original preschool cartoon channel on YouTube Shorts: **Wonder Meadow**
(working channel name *Wonder Meadow Friends*), ages 2–5, English, four short videos a day.

Five original characters — Bobo the bunny, Mimi the cat, Toto the elephant, Zuzu the duck and Lolo the
bear — in calm, kind, one-idea stories: colors, shapes and numbers; letters; friendship; good habits;
gentle adventures; everyday discoveries; original rhymes; bedtime.

Everything is made here: the stories, the drawings, the voices (free speech engines), the music and every
sound effect. Nothing is copied, nothing is bought, and nothing is uploaded without passing the gates below.

What is verified and what is still blocked: [`STATUS.md`](./STATUS.md).

## How it works

```
CEO agent (wonderland/ceo.py)  plans 4 episodes per day, 2 days ahead, and runs a persistent task queue
  │
  ├─ research ─ story ─ storyboard ─ animation ─ sound ─ edit ─ quality control ─ SEO ─ compliance gate
  │                                                                                         │
  │                                                     produced ──(owner approves in review mode)──┤
  │                                                                                         ▼
  ├─ publishing: private upload with a scheduled publish time → verify on YouTube → "published"
  ├─ analytics (real YouTube Analytics only) → improvement (format weights, one-variable experiments)
  └─ health checks · backups · notifications · daily/weekly/monthly reports
```

* **Every task is a row in SQLite** (`state/wonderland.db`). Kill the process at any moment; the next run
  continues where it stopped. Work left "running" by a dead process is handed back after its lease ends.
* **Errors are classified.** Transient → retried with exponential backoff. Permanent → that episode stops,
  the others continue, the owner is told. Blocked (needs a person) → parked and re-checked, never retried blindly.
* **Quality control can say no.** If the finished video fails a technical check (black or frozen picture,
  silence, loudness, length, A/V sync, codecs) the CEO orders a new story for that slot, up to twice, then
  leaves the slot empty. An empty slot is better than a bad or repeated video.
* **Every department answers in the same format**
  `{"agent","task_id","status","output","evidence","errors","next_action"}` and the answer is stored.

| Part | File |
|---|---|
| Orchestrator, queue, recovery | `wonderland/ceo.py`, `wonderland/db.py`, `wonderland/protocol.py` |
| Character bible, world, brand | `config/universe.yaml` |
| Schedule, quality limits, publishing mode, budget | `config/studio.yaml` |
| Stories (formats, dedupe, scoring) | `wonderland/departments/story_formats.py`, `story.py`, `compliance.py` |
| Picture | `wonderland/render/` (2D), `render3d/` (3D toon characters, Three.js) |
| Sound | `wonderland/audio/` (voices, music, sound effects, Foley) |
| Production line | `wonderland/pipeline.py`, `wonderland/departments/production.py` |
| Gates | `departments/qa.py` (technical), `departments/gate.py` (child safety, honesty, licences, made for kids) |
| YouTube | `departments/publishing.py` → `../youtube-automation-os` (official API only) |
| Research, analytics, improvement | `departments/research.py`, `analytics.py`, `improvement.py` |
| Money | `wonderland/finance.py` |
| Health, backups, reports | `wonderland/ops.py` |
| Dashboard | `wonderland/dashboard.py` |

## Run it

```bash
cd wonderland-studio
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-voice.txt
.venv/bin/python -m wonderland voices install     # free neural voice (Kokoro, ~340 MB, once)
.venv/bin/python -m wonderland run-cycle          # plan + produce everything that is due
.venv/bin/python -m wonderland status             # what is ready, what needs you
.venv/bin/python -m wonderland dashboard          # http://127.0.0.1:8095 (read-only)
```

Needs `ffmpeg` on the PATH (`apt install ffmpeg` / `pkg install ffmpeg`).
On the phone (Termux) the studio uses the 2D renderer automatically; the 3D renderer needs Chromium.

Other commands: `worklist`, `episode <id>`, `approve <id>`, `reject <id> "<reason>"`, `report weekly`,
`research "<words>"`, `health`, `backup`, `finance`, `channel-kit`, `daemon` (runs the cycle every 5 minutes
and respects the daily schedule in `studio.yaml`).

## Going live (owner steps — only a person can do these)

1. **Create the channel** in YouTube Studio (the API cannot create channels). `python -m wonderland channel-kit`
   prints the name, About text, keywords and playlists to paste. Set the channel audience to *made for kids*.
   Check that the name is free to use (trademark search) before you commit to it.
2. **Connect YouTube once**: follow `../youtube-automation-os/README.md` (Google Cloud project, Desktop OAuth
   client, `authenticate.py --scopes upload,manage,analytics`). Tokens stay on your device, never in git.
3. **Unlock uploads**: set `YOUTUBE_DRY_RUN=false` in `youtube-automation-os/.env`.
4. **Start in review mode**: `publishing.mode: review` in `config/studio.yaml`. Watch each finished video
   (`status` shows the file), then `python -m wonderland approve <episode>`. The first upload is a controlled
   test: nothing else is uploaded until it is verified on YouTube.
5. Switch to `auto` only when you are happy with a week of approved videos.

Uploads are **private with a scheduled publish time**, so YouTube publishes them on the slot even if the
studio is offline. An episode is marked *published* only after YouTube reports it public.

## Rules the code enforces

* Original characters only; no brands, no existing shows, no copied songs or sounds (licence ledger per episode).
* Child safety lint on every script and every title/description; *made for kids* on every upload.
* No near-duplicates: a story signature never repeats, a format waits 6 episodes, word-trigram similarity ≤ 0.62
  against history and ≤ 0.4 within a day — otherwise the slot is skipped.
* No invented numbers: analytics only from the YouTube Analytics API; impressions, CTR and returning viewers
  are not in the API and are never shown. Research entries carry their source and confidence.
* No spending without permission: paid providers stay off unless `budget.paid_providers_authorized: true`
  and the daily/monthly limits allow it.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

CI job `wonderland` (in `.github/workflows/test.yml`) runs the tests, installs and checks the Kokoro voice,
runs a whole production cycle with publishing off and uploads the episodes as an artifact.
