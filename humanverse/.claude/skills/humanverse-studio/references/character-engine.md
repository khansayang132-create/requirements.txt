# Character engine (scripts/blender/hvchar.py)

One function, `build_character(char)`, turns a cast file into a rigged human. Same input, same character.

## Geometry
- **Body**: a joint graph (pelvis, spine, chest, neck, clavicles, shoulders, elbows, wrists, palm, four 3-joint
  fingers and a 2-joint thumb per hand, hips, knees, ankles, toes) skinned with the Skin modifier and subdivided
  twice: one watertight mesh, so bone-heat weighting works. Proportions come from `height`, `head_ratio`,
  `leg_ratio`, `shoulder_width`, `hip_width`, `thickness`, `belly`, `arm_scale`.
- **Body skin under clothes is removed** after weighting (`mask_covered_skin`), so it can never poke through.
- **Head**: ellipsoid with jaw taper, flattened back, cheeks, joined nose and ears. Eyes: white, iris, pupil and
  an emissive catch-light on an eye bone. Upper lids: half shells on lid bones. Brows on brow bones. Mouth: a
  patch that lies on the face; its shape keys (open, smile, frown, wide, round, closed) are re-projected onto the
  head so lips never sink in.
- **Hair**: cap cut at a sloped hairline plus style pieces: short, ponytail, bun, bob, long, curly, spiky,
  balding; optional beard, mustache, glasses, cap.
- **Clothes**: shirt (long/short sleeves) and trousers/shorts are their own skin meshes with clearance, weighted
  to the same skeleton; shoes, tie and apron are rigid on their bone.

## Rig (41 bones)
root, hips, spine, chest, neck, head; clav/upper_arm/forearm/hand/fingers1/fingers2/thumb per side;
thigh/shin/foot/toe per side; eye, lid, brow per side; IK controls foot_ik, knee_pole, hand_ik per side; `face`.
- Legs: IK (chain 2) to `foot_ik`, pole `knee_pole`. Arms: IK constraint present with influence 0 (FK by default).
- **Axis convention**: every limb/spine bone's Z points forward, so +X swings forward; elbow bend = +X on forearm;
  knee bend = −X on shin; raise arm sideways = +Z (L) / −Z (R). Verified numerically (see tests/).
- **Face controls**: custom properties on `face` drive the mouth shape keys through drivers.

## Weights
`skin_to_rig` runs bone heat, then **measures** it (bone heat can fail silently): unweighted vertices and
left/right leakage. Above 0.5 % / 1 % it replaces the weights with a deterministic two-nearest-bone fallback and
records which method ran in `build_report.json`.

## Identity
The scene builder appends the character collection from `characters/<id>/<id>.blend`; it never rebuilds it.
`hv build-cast` rebuilds a character only when its cast file's sha256 changed (or with `--force`).
