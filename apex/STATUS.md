# APEX status — stage 1

Categories follow the spec's completion gate. Nothing here is described as production-ready.

## IMPLEMENTED (in this repository)

- **Production spec and schemas** (`models.py`): validated spec, script, scene specs and storyboard. Malformed
  input is rejected before any rendering.
- **Scriptwriter** (`script_engine.py`): Anthropic and OpenAI-compatible (OmniRoute, OpenAI) providers; prompt
  with hook, structure and no-fabrication rules; deterministic review (length from spoken form, greeting
  openers, hook length, per-shot length, on-screen text length, unsourced percentages, hashtag count);
  revision loop with a hard limit; script lock with version hashes and changed-scene detection.
- **Narration** (`tts.py`): provider interface; espeak-ng provider; Indonesian number and price
  pronunciation (`Rp25.000` → "dua puluh lima ribu rupiah").
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
- **Deployment files**: `Dockerfile`, `.env.example`, CI job running the full test suite.

## VERIFIED (actually run in the development session)

| Test | Result | Evidence |
|---|---|---|
| Unit + integration suite (48 tests) | PASS locally and in GitHub Actions (`apex` job) | schemas, timing, Indonesian numbers, review, revision limit, locking, mock-server provider call, queue state machine, backoff, dead letter, crash recovery, graceful release, restart, subtitles, publishing states, real ffmpeg edit + QA, QA failure detection, espeak, cache reuse, real Blender render |
| Acceptance sample, end to end (30 s, 9:16, Indonesian, money mistake) | PASS | `samples/money-mistake/output/final.mp4` — 30.83 s, 432×768, 24 fps, H.264 + AAC, SHA-256 `59506ae8…f3d832` |
| Real 3D rendering | PASS | 740 frames, Blender 5.2.3 Cycles CPU, 8 samples + denoise, 36.3 min total (2.94 s/frame on 4 cores) |
| Technical QA on the final file | 16/16 PASS | `output/qa_report.json`: -15.9 LUFS, true peak -1.2 dBFS, no black or silent gaps, valid SRT |
| Run through the persistent queue | PASS | enqueued twice with the same key → one job; worker claimed it, COMPLETED on attempt 1 |
| Graceful worker shutdown | PASS | SIGTERM → "worker stopped", exit in 3 s |
| Selective regeneration | PASS | re-run reused all 6 scene renders (16 s instead of 36 min); a renderer change invalidated the cache as designed |
| Bugs found by these runs and fixed | — | spoken-length estimate ignored expanded prices; subtitle sizes used pixels instead of libass units; headline alignment used ASS numbering instead of SSA; render cache ignored renderer changes; QA crashed on videos without audio; QA let a fully black video pass |
| Creative review | PARTIAL | Claude inspected one frame per scene (notes in `output/manifest.json` → `creative_review_notes`); no vision model runs inside the pipeline yet |
| Docker image build | NOT VERIFIED | The sandbox's network policy denies `deb.debian.org`, so `apt-get` in the image cannot run here. Build it on any normal machine or CI runner. |
| LLM-written script, live | NOT RUN | No API key in this environment (see BLOCKED) |
| Publishing | NOT RUN (by design) | Only the dry-run adapter exists; no production account was touched |

## BLOCKED (needs credentials, accounts or services this session does not have)

| Capability | Blocker | Next action |
|---|---|---|
| LLM-written scripts in the live pipeline | No `ANTHROPIC_API_KEY` / `OMNIROUTE_API_KEY` / `OPENAI_API_KEY` in this environment. The provider code is tested against a local mock server. | Set one key and run without `--script`. OmniRoute already works on the owner's phone. |
| Natural-sounding narration | Only espeak-ng (robotic) is available offline here; neural voice downloads (Hugging Face) are blocked by this sandbox's network policy. | Add an ElevenLabs or other neural TTS provider class behind the `TTSProvider` interface and set its API key. |
| Publishing to TikTok, YouTube, Instagram, Facebook | Each needs an approved developer app plus OAuth credentials for the owner's accounts. | Register a TikTok Content Posting API app and implement its adapter; keep DryRun for tests. |
| Real analytics | Depends on the publishing integrations above. | After publishing works, add metric retrieval per platform. |
| 24/7 hosting | No server is rented. The worker and Docker image exist; a phone can't host Blender rendering. | Rent a VPS with 4+ vCPUs, run the Docker image with a mounted `/data` volume. |
| Licensed music library | None connected. The pipeline uses an original generated pad, so no license issue. | Add a licensed music provider and record license metadata in the manifest. |

## NOT IMPLEMENTED

- Web control center / dashboard (Overview, Script Studio, Storyboard Studio, …). The CLI `status` command
  and the manifest are the current interface.
- AI text-to-video or image-to-video providers (scenes are procedural 3D only), visual consistency bible for
  characters, and characters in general (templates are objects: coins, cup, piggy bank, chart).
- Vision-model creative review of sampled frames (frames are saved for it).
- Content planner, autopilot rules, budgets and spending limits, emergency stop.
- Authentication and roles (no web surface exists yet), backups, multi-language beyond `id`/`en`.
- Additional export profiles (1:1 and 16:9 resolutions exist in the storyboard; only 9:16 was produced).

## Known limits

- Render speed on 4 CPU cores was 2.94 s per 432×768 frame at 8 samples: 36 minutes for a 30 s video at
  24 fps. Output resolution is 432×768; the pipeline does not upscale and claim detail.
- espeak-ng narration is intelligible but robotic: fine for drafts and pipeline tests, not for publishing.
