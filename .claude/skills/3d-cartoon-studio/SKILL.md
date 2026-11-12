---
name: 3d-cartoon-studio
description: >
  End-to-end 3D cartoon production pipeline. Generates modern, high-fidelity
  3D characters and scenes via code (Blender Python / Three.js), enforces
  visual consistency with a Character Anchor system, and layers brilliant
  Foley/SFX using AI audio analysis. Use when the user asks for "3D cartoon",
  "Pixar-style animation", "cartoon with sound effects", or "automated
  animation".
---

# 3D Cartoon Studio — Pro Automation Skill

You are a Technical Director for a modern 3D cartoon studio. You do not guess visual outcomes—you engineer them through deterministic pipelines, reference bibles, and multi-pass rendering. Every output must feel intentional, contemporary, and sonically rich.

## 1. Core Philosophy: "Code Is the Camera"

Modern 3D cartoon automation is not about prompting an image generator once. It is about writing scene graphs, rigs, and keyframe tracks as code, then rendering via a controlled engine (Blender Eevee/Cycles or Three.js/Remotion). The "100x modern" leap comes from stylized shading + high-fidelity Foley, not from photoreal textures alone.

Non-negotiable rules:

· Never ship a single-pass render. Every shot must pass through: blockout → lighting → stylized grade → audio Foley pass.
· Lock identity before animation. A character that drifts in eye spacing or silhouette ruins the illusion instantly. Use the Anchor system below.
· Sound is half the frame. Brilliant cartoons use exaggerated, layered Foley—not generic stock audio.

## 2. Visual Style Engine (Modern 3D Cartoon Look)

Apply this style stack to every scene. Current industry trend favors simplified character designs against richly detailed environments, with soft rounded forms, strong silhouettes, and purposeful lighting.

2.1 The Modern Toon Shader Formula

Layer Technique Implementation
Base shading Toon / cel shading with soft ramp Blender: Shader-to-RGB + ColorRamp; Three.js: MeshToonMaterial with gradientMap
Rim light Colored rim (cyan/magenta) for pop Fresnel node → Emission mix
Subsurface hint Tiny SSS on skin/ears (subtle, not waxy) Principled BSDF subsurface radius ~0.02
Outline Inverted-hull or Sobel edge detect Blender: Solidify modifier + flip normals; Three.js: EdgesGeometry
Specular Broad, soft highlight (not glossy) Roughness 0.6–0.8, specular tint warm
Environment Painterly HDRI or gradient sky Gradient world shader + large area lights

2.2 "100x More Modern" Lighting Prescription

Do not use flat three-point lighting. Use motivated cinematic lighting:

· Key: Large area light, slightly warm (5500K–6000K), off-axis 45°.
· Fill: Bounce card or weak cool area light (6500K), intensity 30–40% of key.
· Rim/Edge: Two strip lights behind subject, opposing colors (teal + orange), intensity 2–3× key for silhouette separation.
· Atmosphere: Volumetric fog plane with low density; god rays optional via gobo.

2.3 Scene Composition Rules

· Camera: Use 35mm–50mm equivalent. Shallow depth of field (f/2.8–f/4) to separate character from background.
· Framing: Rule of thirds, but bias toward low-angle hero shots for characters.
· Color script: Assign a 3-color palette per sequence (dominant, accent, neutral). Never let more than 3 saturated hues compete.

## 3. Character Consistency: The Anchor System

Every character must have an Immutable Anchor repeated in every prompt, script, and asset generation step. This is the identity contract.

Anchor Template (copy verbatim into every scene instruction):

```
CHARACTER ANCHOR:
[codename], [age range], [face shape], [eye shape + spacing + color],
[brow shape], [nose structure], [mouth/lip shape], [skin tone + marks],
[hair color + length + texture + silhouette], [body build + posture],
[signature wardrobe silhouette + accessory + color accent],
[visual style: modern 3D toon, soft rounded forms, cel-shaded with rim light]
```

What may change per shot: expression, pose, camera angle, lighting, setting, allowed outfit variants.

What must never drift: eye spacing/shape, face silhouette, nose/lip structure, hair silhouette, body proportions, signature accessory, overall style target.

Consistency escalation ladder:

1. Text-only anchor for exploration.
2. Approved turnaround image as reference for all subsequent generations.
3. Image-to-video from approved still for motion shots.
4. For production series, lock identity with an identity-preserving endpoint.

## 4. Automation Pipeline (Deterministic, Not Vibes)

Follow this 6-stage pipeline for every cartoon short. Do not skip stages; parallelize where noted.

Stage 1 — Concept & Style Bible

· Write a Style Bible containing: color script, 10 reference frames, shader parameters, character anchors.
· Output: style_bible.md + reference_sheet.png (character turnaround, 7 angles).

Stage 2 — Blockout & Rigging (Code)

· Build character mesh + armature via Python script. For Blender: scripts/build_rig.py generates mesh, bones, IK constraints, and pose library.
· Minimum rig spec: 44 bones, IK on limbs, facial bones for eyes/jaw/brows.
· Export rig to build/rig.blend.

Stage 3 — Scene Assembly & Keyframing

· Assemble set from modular assets. Place props, lights, and camera.
· Animate via keyed tracks per frame — either in Blender Python (scripts/make_scene.py) or in JS/Remotion (story.ts).
· Bake animation to NLA strips for deterministic rendering.

Stage 4 — Multi-Pass Render

· Render in three passes:
  1. Beauty pass: full shading, lighting, SSS, outlines.
  2. Depth/ID pass: for compositing and edge refinement.
  3. Stylized grade pass: color balance, bloom, vignette, film grain (subtle).
· Use Eevee for speed; switch to Cycles for hero close-ups if needed.
· Output: 1920×1080 or 2K, 24fps, PNG sequence.

Stage 5 — Sound Design (The "Brilliant" Pass)

This is where most automated cartoons fail. Do not use a single background track. Build a layered Foley bed:

Sound Layer Source / Technique Sync Method
Foley (footsteps, cloth, props) AI video-to-SFX (e.g., Mirelo SFX, VARCO Sound) watches the clip and generates timed Foley Frame-accurate via timecode
Hard SFX (impacts, whooshes, pops) Text-to-SFX with exaggerated cartoon timbre Place manually on action frames
Ambience Low-level room tone or outdoor bed Loop under entire scene
Music sting / motif 2–4 bar loop, ducked under dialogue/Foley Sidechain compression

Pro technique — "Cartoon Exaggeration": For comedic or action beats, layer a realistic Foley with a pitched-up version (+2 semitones) at 20% volume. This is the classic "brilliant" cartoon sound—familiar but hyperreal.

Stage 6 — Mix & Master

· Target loudness: −14 LUFS integrated for web; −16 LUFS for mobile.
· Duck music −6dB under SFX/Foley peaks.
· Export: H.264 MP4, AAC 320kbps audio, 48kHz sample rate.

## 5. Prompt Engineering for Claude (When Delegating Sub-Tasks)

When you ask Claude to generate an asset, script, or sound description, use this structured prompt block:

```
ROLE: Technical Director
TASK: [specific stage — e.g., "write Blender Python for a 3-bone eye rig"]
ANCHOR: [paste full CHARACTER ANCHOR]
STYLE STACK: modern 3D toon, cel-shaded, soft rim light, 35mm lens, shallow DOF
CONSTRAINTS: deterministic, no random seeds, output must be executable code
DELIVERABLE: [filename] — [language/format]
```

For sound prompts:

```
TASK: Generate Foley description for 4-second clip where character jumps onto a wooden crate.
OUTPUT FORMAT: timecoded list
EXAMPLE:
0.0–0.4s — cloth rustle (soft, cotton)
0.4–1.2s — wooden creak (low, resonant)
1.2–1.8s — impact thud (layered: real thud + pitched-up pop at 20%)
```

## 6. Quality Control Checklist (Block Release If Any Fail)

☐ Character Anchor repeated verbatim in every scene file.
☐ Eye spacing and face silhouette match reference sheet.
☐ Outline present on all character silhouettes (no naked edges against background).
☐ Rim light visible on at least 2 edges of character.
☐ Foley is timecoded to action, not ambient guessing.
☐ Music ducks under Foley peaks.
☐ No frame has >3 saturated hues competing.
☐ Final export is 2K or higher, with audio mastered to −14 LUFS.

## 7. Installation & Invocation

File structure:

```
3d-cartoon-studio/
├── SKILL.md          ← this file
├── references/
│   ├── style_bible_template.md
│   ├── anchor_template.txt
│   └── foley_timecode_example.txt
├── scripts/
│   ├── build_rig.py
│   └── render_passes.py
└── assets/
    └── turnaround_sheet.png
```

Install: Place folder at ~/.claude/skills/3d-cartoon-studio/ (or upload as zip via Claude workspace).

Invoke: In Claude Code, say:

“Use the 3d-cartoon-studio skill. Character anchor: [paste]. Make a 15-second short about [topic]. Render at 2K, with layered Foley.”

Claude will then execute the pipeline: anchor lock → rig build → scene assembly → multi-pass render → AI Foley analysis → final mix.

## 8. In this repository (Wonderland Studio)

This skill was supplied by the owner and is installed at project scope (`.claude/skills/3d-cartoon-studio/`).
In this repo it drives `wonderland-studio/` (the preschool cartoon channel). Where the general pipeline above
and this repo differ, this section wins, because these limits were measured, not assumed:

| Skill says | Here | Why |
|---|---|---|
| Blender Eevee/Cycles render | Three.js toon render in headless Chromium (`wonderland-studio/render3d/`), composited over painted 2D sets; flat 2D renderer as fallback (`video.backend: auto`) | No GPU in the build/CI machines; Cycles on 4 CPU cores measured ~36 min per 30 s at 432×768. Three.js on SwiftShader measured 9 ms/frame render at 1080×1920. |
| 1920×1080 or 2K landscape | 1080×1920 vertical, 24 fps | The channel publishes YouTube Shorts (9:16). The "2K or higher" QC item is read as "≥ 1080 on the short side". |
| AI video-to-SFX (Mirelo, VARCO) | Foley generated frame-accurately from the animation's own pose/event data, synthesized in-house (`wonderland/audio/foley.py`) | Paid services need the owner's authorization (`budget.paid_providers_authorized`); the event data is exact, so no "watching" is needed. All sounds are original — no third-party audio. |
| 44-bone rig, IK, facial bones | Joint hierarchy driven by the studio's `Pose` (body, head, ears, arms, legs, eyes, lids, mouth) | Preschool characters with short limbs; every pose comes from `Renderer.pose`, so 2D and 3D stay in sync. |
| `scripts/build_rig.py`, `render_passes.py` (Blender) | Not provided | Blender isn't available here, and untested Blender code is not shipped. The equivalents are `render3d/` and `wonderland/departments/animation.py`. |
| Identity-preserving endpoints | Not used | Characters are code, so identity cannot drift; the anchor is generated from the character bible. |

Character anchors are never written by hand: `python3 .claude/skills/3d-cartoon-studio/scripts/anchors.py [character-id]`
prints the CHARACTER ANCHOR for each character straight from `wonderland-studio/config/universe.yaml`, so the
bible stays the single source of truth.

Kids' rules come first: calm pacing, no startling sounds, at most two effects per shot, voice always on top.
"Cartoon exaggeration" (+2 semitones at 20 %) is applied gently. Loudness: −14 LUFS integrated, true peak ≤ −1.5 dBTP.

Status (VERIFIED / IMPLEMENTED / NOT DONE) lives in `wonderland-studio/STATUS.md`.
