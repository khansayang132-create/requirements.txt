# Animation workflow (Higgsfield + Wonderland Studio)

| Stage | Tool | Output | Gate |
|---|---|---|---|
| 1 Story | `wonderland` story engine (71 formats, dedupe, compliance) | `story.json` | child-safety lint |
| 2 Character design | `config/universe.yaml` (bible) | anchors (`anchors.py`) | owner approves bible |
| 3 Character references | studio 3D renderer: sheet + 7-angle turnaround | PNGs | eye/silhouette check |
| 4 Environments | studio painted sets; optional Higgsfield stills with references | PNG | ≤ 3 saturated hues |
| 5 Storyboard | `storyboard.py` | timed shots | — |
| 6 Scene stills (optional, paid) | `flux_3_image` / `minimax_h3_image` + reference images + anchor | stills | identity check |
| 7 Video | studio renderer (free, every episode); Higgsfield image-to-video only for special shots | MP4 | — |
| 8 Audio & voice | studio voices + in-house Foley/music (licence ledger) | WAV | voice ≥ 12 dB over bed |
| 9 Edit | `editing.py` (ffmpeg) | final.mp4, captions | — |
| 10 QA | `qa.py` + compliance gate | qa.json | must pass |
| 11 Export | 1080×1920, H.264, AAC 320k 48 kHz, −14 LUFS | MP4 | — |

Daily episodes stay on the free in-house pipeline. Rough paid cost if every episode had 6 Higgsfield video shots of
5 s: 6 × 15 = 90 credits per episode with the cheapest model, 360 credits a day for 4 videos — far beyond the free plan.
Use Higgsfield for selected hero material, and only inside `budget` limits in `config/studio.yaml`.

## Prompt template

```
ROLE: Technical Director
TASK: <stage>
ANCHOR: <output of anchors.py for each character in the shot>
STYLE STACK: modern 3D toon, cel-shaded, soft rim light (teal + warm), ink outlines, 35mm, shallow DOF, calm preschool mood
REFERENCES: <uploaded sheet/turnaround ids> as image_references
CONSTRAINTS: original characters only; no brands; nothing scary; 9:16
```
