# Workflow 02: preview before the full render

Full renders are expensive on CPU (~10-20 s/frame). Before `hv render`:

```bash
python - <<'PY'
import json
for s in ("S01", "S02", "S03"):
    sp = json.load(open(f"project/scenes/{s}/spec.json"))
    print(s, ",".join(str((sh["f0"] + sh["f1"]) // 2) for sh in sp["shots"]))
PY
<blender-python> scripts/blender/render.py -- --blend project/scenes/S01/S01.blend --out /tmp/prev/S01 --frames 39,163,295
```
Make a contact sheet (`hvlib.sheets.sheet`) and look for: exposure, framing (speakers in frame, no cut at joints),
arm/leg poses, props facing camera, character overlap. The first pilot found washed-out exposure, arms folding into
the hips, an edge-on kite and a cropped speaker this way, all before spending hours of render time.
