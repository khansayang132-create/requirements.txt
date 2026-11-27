# NOVA Studio architecture

NOVA Studio turns one idea into a verified production. It sits on top of NOVA's voice engine
(`nova/`: script judge, enhancer, director, TTS adapters, voice cloning, mastering) and adds a
central orchestrator, eight engines, a SQLite database, a persistent scheduler and five screens.

```
idea ─► intent ─► concepts ─► script ─► analysis ─► enhancement ─► emotion ─► voice ─► audio ─► subtitles ─► qa ─► deliver
          E01        E01        E02        E03           E03          E04       E05      E06       E06       QA     history
```

## Central orchestrator (`orchestrator.py`)

- One `productions` row and one `production_stages` row per stage. Each stage reads earlier
  outputs from its checkpoint and writes its own as JSON.
- Transient errors (LLM empty/malformed reply, network) are retried up to 3 times per stage.
  Others stop the production as `failed`; `resume` continues from the first unfinished stage.
- A restart marks running productions `interrupted` (resumable) and running stages `pending`.
- `redo/{stage}` re-runs one stage and the ones after it (e.g. audio after an emotion edit);
  earlier stages are not regenerated.
- `completed` only when the QA stage passed on the final files; otherwise `failed_qa`.
- One worker thread runs productions in order (audio is CPU bound); the API stays responsive.

## Engines and contracts

| Engine | Module | Input → output |
|---|---|---|
| E01 Creative intelligence | `creative.py` | idea, language? → intent {purpose, audience, audience_psychology, structure, perspective, direction, emotional_journey, desired_reaction, content_type, factual}; intent → concepts [{title, angle, audience, hook, message, emotional_direction, duration_s, platform}] |
| E02 Script generation | `scriptgen.py` | intent, concept, seconds → {text, words, target_words, estimated_s, within_target, attempts}. Speaking rates per language (id 120, en 145, ur 130, ar 110 wpm); up to 2 expand/shorten corrections; section-by-section above 350 words |
| E03 Script lab | `lab.py` | text → analysis {score, quality, repetition, sentence_length, pronunciation_difficulty, estimated_s, editor?}; text, mode (8), operation (7), sentence? → {text, accepted, meaning}; compare(a, b) |
| E04 Emotional intelligence | `emotion.py` | text → {arc, sentences: [{emotion (26), intensity, vocal_energy, speed, pitch_direction, delivery, pause_before_ms, pause_after_ms, emphasis, breathing, transition_from_previous, transition_to_next, prosody, engine_emotion, source}]}; edit(one sentence) |
| E05 Voice direction | `voice.py` | adapters (declared capabilities per engine), catalog (profiles + presets), select(language, voice) → {engine, profile_id, preset} |
| E06 Audio production | `pipeline.generate` + `mix.py` | directed segments → mastered WAV/MP3, sentence timeline on the mastered file (via the silence time map), polish (high-pass, compression, de-ess when sibilant), music with ducking, effects |
| E07 Scheduling | `scheduler.py` | jobs (once/daily/weekly/interval, IANA time zone, priority, depends_on, retries) and a content calendar |
| E08 Learning | `learning.py` | stored ratings, versions, edits, metrics → observed findings with sample sizes + labelled suggestions; reset |
| Subtitles | `subtitles.py` | timeline → cues (≤ 2 × 42 chars) → SRT, VTT, JSON, TXT; validation |
| QA | `qa.py` | files + manifest → checks (decode, durations agree, loudness, true peak, dead air, clipping, subtitle coverage/bounds, optional speech recognition) |

LLM output is untrusted text: every field is validated or clipped; rewrites must pass NOVA's
meaning check; factual content types instruct the writer never to invent facts.

## Data (`db.py`, `studio.db`, migrations in order)

projects, ideas, scripts, script_versions, emotional_directions, productions, production_stages,
audio_assets (path, bytes, duration, sample rate, sha256), audio_segments, subtitles,
quality_reports, production_logs, scheduled_jobs, job_runs, content_calendar, notifications,
user_preferences, feedback, performance_metrics. Voice profiles stay in NOVA's encrypted profile
store (Fernet) with their consent records; Studio references them by id.

## Scheduler guarantees

- Jobs are rows, so they survive restarts. Missed occurrences run once after a restart.
- Claim: `UPDATE ... SET lease_until WHERE lease is free AND next_run_utc unchanged`; only one
  worker can win. Each occurrence is a `job_runs` row with UNIQUE(job, scheduled_for, attempt);
  the production carries an idempotency key derived from the same, so it is never made twice.
- A run is `succeeded` only if its production is `completed` with QA passed. Failures retry up
  to `max_retries`, then add a notification.

## Security

- Optional API key for every route (`NOVA_API_KEY`); rate limit on write routes
  (`NOVA_RATE_LIMIT`, default 60/min per client).
- Downloads only from a fixed list of file names inside the production folder.
- Music/effects only from files inside the NOVA data folder; uploads are size-limited and decoded
  through ffmpeg before use.
- Voice cloning needs a consent record naming the speaker; recordings are encrypted at rest.
- Single-user: there is no multi-user account system. The API key is the access control.
