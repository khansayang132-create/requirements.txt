# Animation (scripts/blender/hvanim.py)

`Performer(rig)` turns performance ops into keyframes. Ops in a scene spec:
`walk(path, speed)`, `turn`, `stand`, `idle`, `wave`, `cheer`, `hug_self`, `reach`, `nod`, `slump`, `look(yaw,pitch)`,
`expression(name)`, `say(line_id)`, `cry(f0,f1)`, `blinks`.

## Walking without foot sliding
The rig object travels the path at constant speed. Each foot's IK target is keyed in the rig's frame: during stance
(55 % of the cycle) it moves backward at exactly the travel speed, so it is still in the world; during swing it moves
forward with a lift arc. The stride is kept inside the leg's reach (stride 0.26 × height, hips lowered 4 % while
walking). `foot_slide_report` measures the world motion of each planted ankle afterwards; `hv scenes` refuses
more than 2 cm per frame.

Lesson recorded from the first build: a stride of 0.42 × height planted the target 31 cm from the hip, beyond the
58 cm leg of a child character; IK could not reach it and the ankle slid 2 cm/frame. The gate caught it.

## Face
`EXPRESSIONS` sets mouth controls, brow height/tilt and lid closure for: neutral, happy, laughing, excited, sad,
crying, worried, angry, surprised, confused, embarrassed. Blinks are scheduled every 2–4.5 s. Crying adds tear drops
that roll down the cheeks (`build_scene.add_tears`).

## Lip sync
`hv voice` captures eSpeak NG phoneme events (start time in ms from the engine). `lipsync()` keys one viseme per
phoneme at its midpoint: bilabials close the lips, labiodentals bite, rounded vowels make an O, open vowels open the
jaw, others sit half open; the line's emotion is kept underneath (a smile stays while talking).
