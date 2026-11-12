# Pipeline architecture

`dhfactory run` → `ProductionManagerAgent` → `pipeline/graph.py` runs 14 steps in dependency order. Agents exchange a
typed `ProductionState` (pydantic); each returns an `AgentResult`. State is saved to `jobs/<id>/state.json` after every
step, so a run can be repeated: done steps are skipped, paid steps reuse their provider job id, blocked or failed steps
only block what depends on them.

| Step | Agent | Output |
|---|---|---|
| 01 analyze | production-manager | `SceneSpec` list |
| 02 character | digital-human-director | `characters/<id>/character.json` (fictional by default; a real likeness needs recorded consent) |
| 03 reference images | avatar-engineer | `reference-images/<id>/front.png` |
| 04 identity | digital-human-director | `characters/<id>/identity.json` (anchor, reference hashes, rules) |
| 05 backgrounds | video-engineer | `scenes/<job>/backgrounds/` |
| 06 voice | voice-engineer | `audio/<job>/voice.wav`, `speech_manifest.json` (provider timings when available) |
| 07 talking avatar | avatar-engineer | `scenes/<job>/avatar.mp4` |
| 08 body & expression | avatar-engineer | only where the provider really supports it; otherwise skipped |
| 09 lip sync | avatar-engineer | records who did lip sync; checks clip vs speech length |
| 10 cinematic scenes | video-engineer | image-to-video B-roll (optional) |
| 11–12 assembly & finishing | cinematic-editor | FFmpeg normalize/concat, captions (SRT, burned in), music bed, grade, −14 LUFS |
| 13 QC | quality-control | `rendered-videos/<job>/qc_report.json` |
| 14 export | production-manager | absolute path of `final.mp4`, `jobs/<job>/production_report.json` |

Spend gate (`pipeline/cost_guard.py`): a paid provider runs only with `--approve-spend`, a confirmed price, and an estimate
under `DHF_MAX_SPEND_USD`. FFmpeg is always called with argument lists (no shell).
