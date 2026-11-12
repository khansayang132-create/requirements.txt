# Demo status: V3.0 first production (2026-11-12)

PASS / FAIL / BLOCKED / NOT TESTED, with the evidence for each. Built in a Claude Code cloud sandbox, which has no GPU, no Blender and no provider keys.

## Episode 1: "The Seed That Wouldn't Shine" (Mosslight Valley)

Your v0.3 universe and story were staged for the local engine, with your dialogue kept.
Command: `cartoon-studio run --job ep001 --universe mosslight-valley --episode mosslight-valley-seed-glow-1 --seconds 60`. It took 3 min 24 s.

| Item | Status | Evidence |
|---|---|---|
| Universe import (your JSON untouched) | PASS | `universes/mosslight-valley/universe-bible.json`; sha256 of the 5 `character.json` files identical before and after; test `test_import_keeps_owner_files_and_maps_unique_bodies` |
| 5 character bibles, 3D | PASS | `character-bibles/*/`: front, side and back references, expression, pose and colour sheets, `voice_id.txt`, `bible.json` with sha256 locks; turnarounds checked by eye |
| Seven-act script, child-safety review, staging rule | PASS | `stories/mosslight-valley-seed-glow-1.json`, 15 scenes |
| Storyboard | PASS | `storyboards/mosslight-valley-seed-glow-1.json` |
| Animation, 3D toon (Three.js) | PASS | 1,320 frames; `backend: three` in the job state |
| Voices | PASS, eSpeak | Kokoro's model host is blocked here (Kokoro verified on CI for wonderland-studio); ElevenLabs BLOCKED (no key) |
| Foley, music, mix | PASS | 56 Foley events, −13.9 LUFS, true peak −2.3 dBTP, voice 17.5 dB above the bed |
| Final MP4 | PASS | `rendered-videos/ep001/final.mp4`: 1080×1920, 24 fps, H.264 + AAC 48 kHz, 55.0 s, full decode clean (`cartoon-studio qc`) |
| QC report | PASS | `ep001-qc-report.json`: 25 checks PASS, including duration 55.0 s against a 60 s target ±10 %, lip-sync drift ≤ 0.038 s and bible hashes unchanged |
| Visual identity review | NOT TESTED automatically | Contact sheet and three video frames inspected by eye (Claude). A first render lost Oakley and Morrow from the screen; the staging rule now blocks that, see below |
| External video scenes (Runway, Kling, Higgsfield) | BLOCKED | no keys; step 09 skipped; $0.00 spent |
| FLUX, ComfyUI Cloud, ElevenLabs | BLOCKED | no keys |
| Blender | BLOCKED | not installed |

`final.mp4` (11 MB) is not committed: regenerate it with the command above, or download it from the CI artifact `cartoon-studio-ci-episode`.

## Found by looking, and fixed

The first full render passed every automatic check, but the contact sheet showed the problem: the engine draws only
three characters per shot, so Oakley and Morrow spoke off-screen, and props at the centre were hidden behind a body. The
story writer now refuses any beat with more than three characters, or with a speaker who is not on stage
(`staging_issues`, test `test_staging_rule_catches_hidden_speakers_and_crowds`). The episode was restaged and rendered again.

## Known limitations

- Body plans are stand-ins: moss rabbit → bunny, mushroom fox → cat, pond turtle → elephant, sun-moth → duck, acorn badger → bear. This is recorded in each bible and shown as a warning.
- The boat lands on the grass beside the pond, not on the water. The fireflies are small. The "tangled root" is drawn as a tree.
- Morrow's elephant ears reach past the cell edges of the turnaround sheet.
- The story is a fixed plot. Free-form new stories need either more plots or an LLM story writer behind the same review.
- "Oakley" is also the name of a well-known eyewear brand. Check the trademark before publishing the series.
