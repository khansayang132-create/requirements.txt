# APEX status — stage 1

Categories follow the spec's completion gate. Nothing here is described as production-ready.

## IMPLEMENTED (in this repository)

- **Production spec and schemas** (`models.py`): validated spec, script, scene specs and storyboard. Malformed
  input is rejected before any rendering.
- **Scriptwriter** (`script_engine.py`): Anthropic and OpenAI-compatible (OmniRoute, OpenAI) providers; prompt
  with hook, structure and no-fabrication rules; deterministic review (length from spoken form, greeting
  openers, hook length, per-shot length, on-screen text length, unsourced percentages, hashtag count);
  revision loop with a hard limit; script lock with version hashes and changed-scene detection.
- **Narration** (`tts.py`): provider interface; ElevenLabs provider (used when `ELEVENLABS_API_KEY` is set) and
  espeak-ng fallback; Indonesian number and price pronunciation (`Rp25.000` → "dua puluh lima ribu rupiah").
- **Storyboard** (`storyboard.py`, `timing.py`): scene timing from measured narration, snapped to whole frames,
  with a gate that fails the job if the timeline misses target ± tolerance.
- **3D rendering** (`render3d.py`): five procedural Blender scenes, six camera moves, studio lighting, depth of
  field, Cycles path tracing. Renders are cached per scene; the cache key includes the renderer's source hash,
  so changing the renderer re-renders and changing one scene re-renders only that scene.
- **Editor** (`assemble.py`): scene clips with fades, narration placed per scene, an original procedurally
  generated music bed, sidechain ducking, -14 LUFS loudness, captions and headlines placed clear of the 9:16
  platform UI.
- **Technical QA** (`qa.py`): ffprobe streams, resolution, frame rate, codec, pixel format, duration vs
  storyboard and target, black-frame detection, silence detection, EBU R128 loudness, true-peak clipping,
  subtitle syntax, scene count, and one sampled frame per scene. Creative review is reported separately as
  NOT RUN, never folded into the technical score.
- **Automatic repair** (`pipeline.py`): one rebuild of the edit from cached assets when QA fails, then re-check;
  attempts are recorded in the manifest.
- **Persistent queue and worker** (`jobs.py`, `cli.py`): SQLite with the spec's job states, validated
  transitions, idempotency keys, leases with heartbeats, recovery of jobs from dead workers, exponential
  backoff, dead letters with the last error, graceful shutdown, and an audit log of every state change.
- **Manifest and metadata**: every export records spec, script version and provenance, render settings per
  scene, providers and their quality notes, music source, output SHA-256 hashes, QA summary, repairs and stage
  timings; `metadata.json` holds caption, hashtags and the thumbnail concept.
- **Publishing state machine** (`publishing.py`): DRAFT → … → PUBLISHED, with FAILED, CANCELLED,
  REQUIRES_AUTHORIZATION and PUBLICATION_STATUS_UNKNOWN. A dry-run adapter writes the upload package and
  can never mark a post PUBLISHED.
- **Autopilot governance** (`autopilot.py`): policy file with emergency stop (`stop` / `resume`; workers take no new
  jobs while paused), a daily job cap counted from the queue, allowed/prohibited topic keywords, and an approval
  gate. Safe defaults when no policy file exists (approval required, 3 jobs/day).
- **Content planner** (`apex.cli plan`): turns a plan file into jobs, only for approved, compliant entries within
  the daily cap; entry ids are idempotency keys, so re-running a plan never duplicates work. Every entry gets a
  decision: ENQUEUED, EXISTS, WAITING_FOR_APPROVAL, REJECTED, DEFERRED or SKIPPED.
- **Control center** (`dashboard.py`, `apex.cli dashboard`): read-only web page with autopilot state, queue counts,
  recent jobs, per-job history, QA result and the finished video (with byte-range streaming), plus `/health`.
  Binds to 127.0.0.1; serves only video paths a completed job recorded.
- **Idea generation** (`ideas.py`, `apex.cli ideas`): an LLM proposes ideas for the channel's niche; fixed
  checks reject slow-greeting hooks, prohibited topics, near-duplicates of the plan or queue, unknown angles,
  more than two ideas per angle per batch, and lengths outside 15-90 s. Survivors are appended to the plan
  with `"approved": false`; `apex.cli approve --id ...` approves them. Nothing is approved automatically.
- **Vision creative review** (`vision.py`, `apex.cli review`): sends the sampled frames, with each scene's
  narration and on-screen text, to a vision model. The model returns scores and notes. PASS / NEEDS_WORK is
  computed locally (overall >= 7, no frame < 5, every frame matches its scene, every frame reviewed). The
  result is advisory and is written into `qa/qa_report.json` and `manifest.json`.
- **Backups** (`backup.py`, `apex.cli backup` / `verify-backup`): consistent SQLite online-backup snapshot of
  the queue plus policy and plan files, SHA-256 manifest, integrity check on verify, rotation (default 14).
- **Headroom routing**: with `HEADROOM_BASE_URL` set, script, idea and vision calls go through the Headroom
  proxy first and fall back to the direct gateway only when Headroom can't be reached.
- **Deployment files**: `Dockerfile`, `.env.example`, CI job running the full test suite.

## VERIFIED (actually run in the development session)

| Test | Result | Evidence |
|---|---|---|
| Unit + integration suite (93 tests) | PASS locally and in GitHub Actions (`apex` job) | schemas, timing, Indonesian numbers, decimal-comma and shorthand (rb/jt/k) amounts, review, revision limit, locking, mock-server provider call, queue state machine, backoff, dead letter, crash recovery, graceful release, restart, subtitles, publishing states, real ffmpeg edit + QA, QA failure detection, espeak (incl. dash-leading narration), cache reuse, real Blender render |
| Acceptance sample, end to end (30 s, 9:16, Indonesian, money mistake) | PASS | `samples/money-mistake/output/final.mp4` — 30.83 s, 432×768, 24 fps, H.264 + AAC, SHA-256 `59506ae8…f3d832` |
| Real 3D rendering | PASS | 740 frames, Blender 5.2.3 Cycles CPU, 8 samples + denoise, 36.3 min total (2.94 s/frame on 4 cores) |
| Technical QA on the final file | 16/16 PASS | `output/qa_report.json`: -15.9 LUFS, true peak -1.2 dBFS, no black or silent gaps, valid SRT |
| Run through the persistent queue | PASS | enqueued twice with the same key → one job; worker claimed it, COMPLETED on attempt 1 |
| Autopilot + planner + dashboard | PASS | approval gate, prohibited topic, daily cap, idempotent re-plan, paused plan; a real worker process left a queued job alone while paused; dashboard pages, `/health`, byte ranges (206/416) and path-traversal attempts (404) tested; dashboard run against the real queue from the 36-min render shows its full CREATED → COMPLETED history |
| Ideas, approval, vision review, backups, Headroom fallback | PASS (against local stub servers) | review rules on a mixed batch (greeting, banned topic, near-duplicate, invalid length); generated ideas stay WAITING_FOR_APPROVAL until `approve`; CLI `ideas` → `approve` → `plan` enqueues only the approved one; vision request carries every frame as a data URI plus scene text; a reply without scores is refused and leaves review NOT RUN; backups taken while another thread writes pass `integrity_check`; tampered files are caught; Headroom down → direct route, direct down → Headroom |
| 16:9 and 1:1 exports | PASS (draft quality: 12 fps, 2 samples) | the sample script rendered end to end in both shapes: 768×432 in 11.5 min and 720×720 in 16.6 min, each 30.75 s H.264 + AAC with 16/16 technical QA; frames checked by eye: headline at the top, captions above the player's control bar, subjects framed in both shapes |
| Graceful worker shutdown | PASS | SIGTERM → "worker stopped", exit in 3 s |
| Selective regeneration | PASS | re-run reused all 6 scene renders (16 s instead of 36 min); a renderer change invalidated the cache as designed |
| Bugs found by these runs and fixed | — | spoken-length estimate ignored expanded prices; subtitle sizes used pixels instead of libass units; headline alignment used ASS numbering instead of SSA; render cache ignored renderer changes; QA crashed on videos without audio; QA let a fully black video pass |
| Creative review | PARTIAL | `apex.cli review` exists and is tested against a stub; not yet run against a live vision model (no key here). Claude inspected one frame per scene of the sample by hand (notes in `output/manifest.json` → `creative_review_notes`) |
| Ideas from a live LLM | NOT RUN | No API key in this environment; tested against a stub |
| Docker image build | NOT VERIFIED | The sandbox's network policy denies `deb.debian.org`, so `apt-get` in the image cannot run here. Build it on any normal machine or CI runner. |
| LLM-written script, live | NOT RUN | No API key in this environment (see BLOCKED) |
| Publishing | NOT RUN (by design) | Only the dry-run adapter exists; no production account was touched |

## BLOCKED (needs credentials, accounts or services this session does not have)

| Capability | Blocker | Next action |
|---|---|---|
| LLM-written scripts in the live pipeline | No `ANTHROPIC_API_KEY` / `OMNIROUTE_API_KEY` / `OPENAI_API_KEY` in this environment. The provider code is tested against a local mock server. | Set one key and run without `--script`. OmniRoute already works on the owner's phone. |
| Natural-sounding narration | `ElevenLabsProvider` is implemented and tested against a local stub (key header, voice path, spoken-form text, 402 → not retried, unreachable → retried). Live use is blocked three ways: the owner's ElevenLabs subscription has an unpaid invoice (all 6 test clips were refused on 2026-10-22), no `ELEVENLABS_API_KEY` is set on a machine running APEX, and this sandbox's network policy denies `api.elevenlabs.io`. | Pay the ElevenLabs invoice, set `ELEVENLABS_API_KEY` where APEX runs (voice defaults to Nilasari), re-run the sample. |
| Publishing to TikTok, YouTube, Instagram, Facebook | Each needs an approved developer app plus OAuth credentials for the owner's accounts. | Register a TikTok Content Posting API app and implement its adapter; keep DryRun for tests. |
| Real analytics | Depends on the publishing integrations above. | After publishing works, add metric retrieval per platform. |
| 24/7 hosting | No server is rented. The worker and Docker image exist; a phone can't host Blender rendering. | Rent a VPS with 4+ vCPUs, run the Docker image with a mounted `/data` volume. |
| Licensed music library | None connected. The pipeline uses an original generated pad, so no license issue. | Add a licensed music provider and record license metadata in the manifest. |

## NOT IMPLEMENTED

- Editing from the dashboard (it is read-only), and the spec's other studio pages (Script Studio, Storyboard
  Studio, Asset Library). Changes go through the CLI.
- AI text-to-video or image-to-video providers (scenes are procedural 3D only), visual consistency bible for
  characters, and characters in general (templates are objects: coins, cup, piggy bank, chart).
- Spending budgets in money (the daily job cap limits volume, not cost).
- Scheduled idea generation (run `apex.cli ideas` yourself or from cron; it never approves).
- Authentication and roles (the only web surface is read-only and bound to localhost), off-machine backup
  copies (backups are local directories), multi-language beyond `id`/`en`.

## Known limits

- Render speed on 4 CPU cores was 2.94 s per 432×768 frame at 8 samples: 36 minutes for a 30 s video at
  24 fps. Output resolution is 432×768; the pipeline does not upscale and claim detail.
- espeak-ng narration is intelligible but robotic: fine for drafts and pipeline tests, not for publishing.
