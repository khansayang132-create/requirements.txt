# APEX: autonomous short-video production (stage 1)

APEX turns a production spec into a finished, QA-checked vertical video:

```
spec ─► script (LLM or approved file) ─► review + bounded revision ─► LOCK (versioned)
     ─► narration TTS per scene ─► storyboard (timed from measured audio, validated)
     ─► procedural 3D scenes rendered in Blender Cycles (cached per scene)
     ─► edit: clips + narration + generated music bed + ducking + loudness + subtitles/headlines
     ─► technical QA (ffprobe, black/silence detection, EBU R128, subtitle syntax) + 1 safe repair
     ─► manifest (hashes, providers, settings, provenance) + platform metadata
```

It runs once from the command line, or continuously as a worker on a persistent job queue.

## Quick start

Needs Python 3.13, ffmpeg, espeak-ng and the DejaVu fonts.

```
cd apex
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo apt-get install -y ffmpeg espeak-ng fonts-dejavu-core

# One video, directly:
.venv/bin/python -m apex.cli run --spec samples/money-mistake/spec.json \
    --script samples/money-mistake/script.json --project out/money --fps 24 --samples 8

# Or through the queue + 24/7 worker:
.venv/bin/python -m apex.cli enqueue --spec samples/money-mistake/spec.json \
    --script samples/money-mistake/script.json --project out/money --db out/jobs.db
.venv/bin/python -m apex.cli worker --db out/jobs.db      # Ctrl+C / SIGTERM stops it cleanly
.venv/bin/python -m apex.cli status --db out/jobs.db

# Autopilot: a plan file in, only approved and allowed entries out, within the daily cap.
.venv/bin/python -m apex.cli policy --db out/jobs.db --max-per-day 3 --prohibit "judi,pinjol"
.venv/bin/python -m apex.cli plan --plan plan.json --db out/jobs.db
.venv/bin/python -m apex.cli stop --db out/jobs.db       # emergency stop; `resume` to continue
.venv/bin/python -m apex.cli dashboard --db out/jobs.db  # http://127.0.0.1:8787 (read-only)
```

A plan file is a JSON list:
`[{"id": "coffee-1", "approved": true, "spec": "samples/money-mistake/spec.json",
"script": "samples/money-mistake/script.json"}]`. The `id` is the idempotency key.

Leave out `--script` to have an LLM write the script. That needs `ANTHROPIC_API_KEY`, or
`OMNIROUTE_API_KEY` (your OmniRoute gateway), or `OPENAI_API_KEY` (see `.env.example`).

Narration uses ElevenLabs when `ELEVENLABS_API_KEY` is set (default voice: Nilasari, Indonesian), and the
offline espeak-ng voice otherwise.

Docker: `docker build -t apex-worker . && docker run -v $PWD/data:/data apex-worker`
(the worker reads and writes `/data/jobs.db`).

Tests: `.venv/bin/python -m pytest -q` (64 tests)

## Modules

| Module | What it does |
|---|---|
| `models.py` | Validated schemas: production spec, script, scene specs, storyboard, job states and allowed transitions |
| `script_engine.py` | Anthropic / OpenAI-compatible (OmniRoute) providers, deterministic script review, bounded revision loop, script locking with changed-scene detection |
| `tts.py` | TTS provider interface, ElevenLabs and espeak-ng providers (`tts_from_env`), Indonesian number/price pronunciation |
| `timing.py`, `storyboard.py` | Scene timing from measured narration, snapped to frames; target-length gate |
| `render3d.py` | Procedural Blender scenes (`hero_coin`, `coffee_cup`, `coin_stack`, `bar_chart`, `piggy_bank`), 6 camera moves, Cycles path tracing |
| `assemble.py` | ffmpeg edit: clips, fades, narration placement, generated music bed, sidechain ducking, -14 LUFS, captions + headlines in the 9:16 safe zone |
| `qa.py` | Technical QA checks and sampled frames; creative review reported separately as NOT RUN |
| `jobs.py` | SQLite queue: idempotency keys, leases + heartbeats, crash recovery, exponential backoff, dead letters, audit log |
| `pipeline.py` | Stage orchestration, per-scene render cache, one automatic repair, production manifest |
| `publishing.py` | Post state machine; dry-run adapter only (never marks PUBLISHED without provider confirmation) |
| `autopilot.py` | Policy (emergency stop, daily cap, allowed/prohibited topics, approval gate) and the content planner |
| `dashboard.py` | Read-only control center: queue, job history, QA, video playback, `/health` |
| `cli.py` | `run`, `enqueue`, `worker`, `status`, `plan`, `stop`, `resume`, `policy`, `dashboard` |

## Status (stage 1)

See [`STATUS.md`](STATUS.md) for what is implemented, verified, blocked and not implemented.
