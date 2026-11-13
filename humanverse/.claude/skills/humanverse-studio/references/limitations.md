# Limitations (version 1.0)

- **Look**: stylised "toy" humans built from procedural primitives. Clean and consistent, not a feature-film
  sculpt. No textures, no cloth or hair simulation; hair is solid geometry.
- **Fingers** are one curl chain for four fingers plus a thumb, not individual finger bones.
- **Jaw**: the mouth opens through shape keys on a mouth patch; the head mesh itself does not deform (no jaw bone
  geometry), and there are no teeth or tongue.
- **Body contact**: hugs between two characters, sitting, and hand-to-hand contact are not solved (arm IK exists,
  but no contact planner). Clipping between characters is not measured.
- **Voice** is eSpeak NG (robotic) unless Piper and a voice model are installed locally.
- **Rendering** on a CPU-only machine is slow (~12 s/frame at 720p); long films need a GPU or patience.
- **MakeHuman / MPFB2 and ComfyUI are not integrated**: not installed on the build machine, and nothing here needs
  them. A MakeHuman base mesh could replace `build_body` later; the rig, weights checks and QA would stay.
