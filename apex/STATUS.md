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

See the "Verification log" section at the end of this file.

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

- Render speed on 4 CPU cores is about 3–5 s per 432×768 frame at 8 samples, so a 30 s video at 24 fps
  takes roughly 40–60 minutes. Output resolution is 432×768; the pipeline does not upscale and claim detail.
- espeak-ng narration is intelligible but robotic: fine for drafts and pipeline tests, not for publishing.
