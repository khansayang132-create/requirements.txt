# QA checklist (`hv qa`)

| Area | Check | How it is proven |
|---|---|---|
| Character | model exists | `.blend` starts with `BLENDER` |
| Character | exports | `.glb` magic `glTF`; `.fbx` header `Kaydara FBX Binary` |
| Character | geometry / materials | build report: > 5,000 vertices and polygons; ≥ 10 materials |
| Character | identity documented | the 7 identity files exist |
| Character | references | front/side/back/three-quarter + 5 expressions are valid PNGs |
| Rig | armature | ≥ 30 bones, ≥ 20 deform |
| Rig | weights | unweighted < 0.5 %, cross-side < 1 % (measured, per mesh) |
| Rig | deformation | 8 poses: no non-finite vertex, ≤ 0.2 % of edges stretched beyond 0.25–2.5× |
| Storyboard | complete + approved | 14 fields per shot, approver recorded |
| Voice | per line | RMS > 0.02, ≥ 3 phoneme events |
| Animation | data, lip sync, feet | fcurves per rig > 50; ≥ 3 visemes per line; planted feet < 2 cm/frame |
| Render | frames | every PNG present with valid CRCs |
| Audio | scene mixes | no clipped samples; no silence > 1.5 s |
| Video | final | decodes end to end; H.264 yuv420p; delivery size; fps; duration = edit ± 0.2 s; no black > 1 s; subtitle track |
| Audio | final | AAC; A/V stream lengths within 0.1 s; −16 LUFS ± 1, true peak ≤ −1.0 dBTP; every cue inside the movie |

Not machine-tested (say so): acting quality, appeal, lip shapes against a phoneme recogniser.
