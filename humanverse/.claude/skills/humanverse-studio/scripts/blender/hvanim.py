"""HUMANVERSE animation engine: real keyframes on the character rig.

Bone conventions (set by hvchar): limb/spine bones have Z pointing forward, so +X rotation swings a bone forward;
a knee bends with -X on the shin; raising an arm sideways is +Z on upper_arm.L and -Z on upper_arm.R.
Eye bones: +X looks up, +Z looks to the character's left. Lid bones: -X closes. Brow bones: location Z raises.

Body travel moves the rig object along a path at constant speed; feet are on leg IK, and a planted foot is keyed
backward in the character's frame at exactly the travel speed, so it stays still in the world (no foot sliding).
`foot_slide_report` measures that afterwards from the evaluated bones.
"""

from __future__ import annotations

import math
import random

import bpy
from mathutils import Vector

R = math.radians

EXPRESSIONS = {
    #             smile  frown  open  wide  round  brow_up  brow_tilt  lid  (lid: 0 open .. 1 closed)
    "neutral":   (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    "happy":     (0.9, 0.0, 0.1, 0.1, 0.0, 0.25, 0.0, 0.1),
    "laughing":  (0.8, 0.0, 0.7, 0.5, 0.0, 0.5, 0.0, 0.45),
    "excited":   (0.7, 0.0, 0.45, 0.3, 0.0, 0.8, 0.0, 0.0),
    "sad":       (0.0, 0.8, 0.0, 0.0, 0.0, 0.2, 0.9, 0.3),
    "crying":    (0.0, 1.0, 0.35, 0.2, 0.0, 0.3, 1.0, 0.55),
    "worried":   (0.0, 0.45, 0.05, 0.0, 0.0, 0.45, 0.8, 0.1),
    "angry":     (0.0, 0.6, 0.15, 0.3, 0.0, -0.3, -1.0, 0.25),
    "surprised": (0.0, 0.0, 0.1, 0.0, 1.0, 1.0, 0.0, -0.1),
    "confused":  (0.0, 0.3, 0.05, 0.0, 0.3, 0.6, 0.5, 0.05),
    "embarrassed": (0.45, 0.0, 0.0, 0.0, 0.0, 0.3, 0.6, 0.35),
}
MOUTH_KEYS = ("smile", "frown", "open", "wide", "round", "closed")


class Performer:
    def __init__(self, rig, fps: int = 24, seed: str = ""):
        self.rig = rig
        self.pb = rig.pose.bones
        self.fps = fps
        self.H = (rig.data.bones["head"].tail_local.z)
        self.rng = random.Random(seed or rig.name)
        self.face = {k: 0.0 for k in MOUTH_KEYS}
        self.expr = "neutral"
        self.stance_frames: dict[str, list[int]] = {"L": [], "R": []}
        # IK targets must sit at ankle height or the leg cannot reach them and the ankle slides
        b = rig.data.bones
        self.ankle_dz = b["shin.L"].tail_local.z - b["foot_ik.L"].head_local.z
        if not rig.animation_data:
            rig.animation_data_create()
        if not rig.animation_data.action:
            rig.animation_data.action = bpy.data.actions.new(rig.name + "_perf")

    # ------------------------------------------------------------------ low level
    def rot(self, bone, frame, x=0.0, y=0.0, z=0.0):
        p = self.pb[bone]
        p.rotation_euler = (x, y, z)
        p.keyframe_insert("rotation_euler", frame=frame)

    def loc(self, bone, frame, v):
        p = self.pb[bone]
        p.location = v
        p.keyframe_insert("location", frame=frame)

    def prop(self, name, frame, value):
        self.pb["face"][name] = float(value)
        self.pb["face"].keyframe_insert('["%s"]' % name, frame=frame)

    def place(self, frame, x, y, heading_deg=0.0):
        """heading 0 = facing -Y (towards a default camera); 90 = facing +X."""
        self.rig.location = (x, y, 0)
        self.rig.rotation_euler = (0, 0, R(heading_deg))
        self.rig.keyframe_insert("location", frame=frame)
        self.rig.keyframe_insert("rotation_euler", frame=frame)

    # ------------------------------------------------------------------ body poses
    def stand(self, frame, arms_down=34, weight=0.0):
        """Relaxed standing pose from the A-pose rest: arms lowered, slight elbow bend, feet under hips."""
        for s, sg in (("L", 1), ("R", -1)):
            self.rot("upper_arm." + s, frame, x=R(4), z=-sg * R(arms_down))
            self.rot("forearm." + s, frame, x=R(12))
            self.rot("hand." + s, frame)
            self.rot("fingers1." + s, frame, x=R(10))
            self.rot("fingers2." + s, frame, x=R(12))
            a = self.rig.data.bones["foot_ik." + s].head_local
            self.loc("foot_ik." + s, frame, (0, 0, self.ankle_dz))
        self.loc("hips", frame, (0, 0, 0))
        self.rot("hips", frame, z=R(weight))
        for b in ("spine", "chest", "neck", "head"):
            self.rot(b, frame)

    def idle(self, f0, f1, energy=1.0):
        """Breathing and small weight shifts between f0 and f1 (keys every ~half second)."""
        step = max(6, self.fps // 2)
        for f in range(f0, f1 + 1, step):
            ph = 2 * math.pi * (f - f0) / (self.fps * 3.2)
            self.rot("chest", f, x=R(1.2 * math.sin(ph) * energy))
            self.rot("spine", f, z=R(1.5 * math.sin(ph * 0.5) * energy))
            self.rot("head", f, x=R(1.5 * math.sin(ph * 0.7 + 1) * energy), y=R(3 * math.sin(ph * 0.33) * energy))

    def walk(self, f0, path, speed=None, stride=None):
        """Walk along world-space path [(x, y), ...] starting at frame f0; returns the end frame."""
        H = self.H
        speed = speed or H * 0.75                                   # m/s, scales with size
        stride = stride or H * 0.26                                 # one step length (kept inside leg reach)
        pts = [Vector((x, y, 0)) for x, y in path]
        segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        total = sum((b - a).length for a, b in segs)
        frames = max(2, int(round(total / speed * self.fps)))
        cycle = 2 * stride / speed * self.fps                       # frames per left+right cycle
        lift = H * 0.05
        STANCE = 0.55
        travel = speed * STANCE * cycle / self.fps                  # distance a planted foot covers: equals body travel
        for i in range(frames + 1):
            f = f0 + i
            d = total * i / frames
            for a, b in segs:
                L = (b - a).length
                if d <= L + 1e-6:
                    pos = a + (b - a) * (d / max(L, 1e-9))
                    dirv = (b - a).normalized()
                    break
                d -= L
            heading = math.degrees(math.atan2(dirv.x, -dirv.y))
            self.rig.location = pos
            self.rig.rotation_euler = (0, 0, R(heading))
            self.rig.keyframe_insert("location", frame=f)
            self.rig.keyframe_insert("rotation_euler", frame=f)
            ramp = min(1.0, i / (self.fps * 0.35), (frames - i) / (self.fps * 0.35))
            for s, off in (("L", 0.0), ("R", 0.5)):
                ph = ((i / cycle) + off) % 1.0
                if ph < STANCE:                                     # stance: foot moves back at travel speed
                    u = ph / STANCE
                    y = (u - 0.5) * travel
                    z = 0.0
                    self.stance_frames[s].append(f)
                else:                                               # swing: forward with a lift
                    u = (ph - STANCE) / (1 - STANCE)
                    y = (0.5 - u) * travel
                    z = math.sin(u * math.pi) * lift
                self.loc("foot_ik." + s, f, self._ik_local(s, y, z))
                sw = math.sin(2 * math.pi * ((i / cycle) + off))
                sg = 1 if s == "L" else -1
                self.rot("upper_arm." + s, f, x=R(-22 * sw * ramp + 4), z=-sg * R(34))
                self.rot("forearm." + s, f, x=R(18 + 10 * max(0, -sw) * ramp))
            bob = abs(math.cos(2 * math.pi * i / cycle))
            self.loc("hips", f, (0, -(H * 0.04 + H * 0.012 * bob) * ramp, 0))
            self.rot("hips", f, y=R(6 * math.sin(2 * math.pi * i / cycle) * ramp))
            self.rot("chest", f, y=R(-7 * math.sin(2 * math.pi * i / cycle) * ramp), x=R(3 * ramp))
        return f0 + frames

    def _ik_local(self, side, fwd_back, up):
        """foot_ik bone-local offset: the bone points -Y with Z up, so local +Y is world-forward in the rig frame."""
        return (0, -fwd_back, up + self.ankle_dz)

    def turn_to(self, f0, f1, heading_deg):
        cur = self.rig.rotation_euler.z
        self.rig.keyframe_insert("rotation_euler", frame=f0)
        self.rig.rotation_euler = (0, 0, R(heading_deg))
        self.rig.keyframe_insert("rotation_euler", frame=f1)
        del cur

    # ------------------------------------------------------------------ gestures
    def wave(self, f0, f1, side="R"):
        sg = 1 if side == "L" else -1
        self.rot("upper_arm." + side, f0, x=R(4), z=-sg * R(34))
        up = f0 + 6
        self.rot("upper_arm." + side, up, x=R(10), z=sg * R(70))
        for k, f in enumerate(range(up, f1 - 6, 5)):
            self.rot("forearm." + side, f, x=R(20), y=0, z=sg * R(25 if k % 2 else -25))
            self.rot("hand." + side, f, z=sg * R(15 if k % 2 else -15))
        self.rot("upper_arm." + side, f1 - 6, x=R(10), z=sg * R(70))
        self.rot("upper_arm." + side, f1, x=R(4), z=-sg * R(34))
        self.rot("forearm." + side, f1, x=R(12))
        self.rot("hand." + side, f1)

    def gesture_talk(self, f0, f1, side="L", amount=1.0):
        """Open-palm emphasis while speaking."""
        sg = 1 if side == "L" else -1
        mid = (f0 + f1) // 2
        self.rot("upper_arm." + side, f0, x=R(4), z=-sg * R(34))
        self.rot("forearm." + side, f0, x=R(12))
        self.rot("upper_arm." + side, mid, x=R(25 * amount), z=-sg * R(24))
        self.rot("forearm." + side, mid, x=R(55 * amount), y=sg * R(-30 * amount))
        self.rot("upper_arm." + side, f1, x=R(4), z=-sg * R(34))
        self.rot("forearm." + side, f1, x=R(12))

    def cheer(self, f0, f1):
        """Both arms up and a small hop."""
        H = self.H
        for s, sg in (("L", 1), ("R", -1)):
            self.rot("upper_arm." + s, f0, x=R(4), z=-sg * R(34))
            self.rot("upper_arm." + s, f0 + 6, x=R(10), z=sg * R(95))
            self.rot("forearm." + s, f0 + 6, x=R(10))
            self.rot("upper_arm." + s, f1 - 4, x=R(10), z=sg * R(95))
            self.rot("upper_arm." + s, f1, x=R(4), z=-sg * R(34))
            self.rot("forearm." + s, f1, x=R(12))
        for k, f in enumerate(range(f0 + 4, f1 - 4, 8)):
            z = H * 0.05 if k % 2 == 0 else 0.0
            self.loc("hips", f, (0, z * 0.0, 0))
            for s in ("L", "R"):
                self.loc("foot_ik." + s, f, self._ik_local(s, 0, z))
            self.loc("root_lift", f, z) if False else None
        for s in ("L", "R"):
            self.loc("foot_ik." + s, f1, self._ik_local(s, 0, 0))

    def hug_self(self, f0, f1):
        """Arms wrap the chest (comforting / crying)."""
        for s, sg in (("L", 1), ("R", -1)):
            self.rot("upper_arm." + s, f0, x=R(4), z=-sg * R(34))
            self.rot("upper_arm." + s, f0 + 8, x=R(48), z=-sg * R(20))
            self.rot("forearm." + s, f0 + 8, x=R(100))
            self.rot("upper_arm." + s, f1 - 8, x=R(48), z=-sg * R(20))
            self.rot("forearm." + s, f1 - 8, x=R(100))
            self.rot("upper_arm." + s, f1, x=R(4), z=-sg * R(34))
            self.rot("forearm." + s, f1, x=R(12))

    def reach(self, f0, f1, side="R", fwd=60, raise_=20):
        sg = 1 if side == "L" else -1
        self.rot("upper_arm." + side, f0, x=R(4), z=-sg * R(34))
        self.rot("upper_arm." + side, f0 + 8, x=R(fwd), z=-sg * R(30 - raise_))
        self.rot("forearm." + side, f0 + 8, x=R(15))
        self.rot("upper_arm." + side, f1 - 8, x=R(fwd), z=-sg * R(30 - raise_))
        self.rot("upper_arm." + side, f1, x=R(4), z=-sg * R(34))
        self.rot("forearm." + side, f1, x=R(12))

    def nod(self, f0, times=2):
        for k in range(times):
            self.rot("head", f0 + k * 8, x=R(0))
            self.rot("head", f0 + k * 8 + 4, x=R(12))
        self.rot("head", f0 + times * 8, x=R(0))

    def slump(self, f0, f1, amount=1.0):
        """Sad posture: head down, shoulders forward."""
        for f, k in ((f0, 0.0), (f0 + 10, amount), (f1 - 10, amount), (f1, 0.0)):
            self.rot("chest", f, x=R(10 * k))
            self.rot("neck", f, x=R(12 * k))
            self.rot("head", f, x=R(10 * k))
            for s, sg in (("L", 1), ("R", -1)):
                self.rot("clav." + s, f, x=R(10 * k))

    def look(self, frame, yaw_deg=0.0, pitch_deg=0.0, head=True):
        if head:
            self.rot("head", frame, x=R(-pitch_deg * 0.5), y=R(yaw_deg * 0.6))
        for s in ("L", "R"):
            self.rot("eye." + s, frame, x=R(pitch_deg * 0.5), z=R(yaw_deg * 0.4))

    # ------------------------------------------------------------------ face
    def expression(self, frame, name, blend=6, hold_mouth=False):
        sm, fr, op, wi, ro, bu, bt, lid = EXPRESSIONS[name]
        er = self.H * 0.012
        for f, k in ((frame - blend, None), (frame, 1.0)):
            if k is None:
                for kname in MOUTH_KEYS:
                    if not hold_mouth:
                        self.prop(kname, f, self.face[kname])
                continue
        vals = {"smile": sm, "frown": fr, "open": op, "wide": wi, "round": ro, "closed": 0.0}
        if not hold_mouth:
            for kname, v in vals.items():
                self.prop(kname, frame, v)
                self.face[kname] = v
        for s, sg in (("L", 1), ("R", -1)):
            self.loc("brow." + s, frame, (0, 0, bu * er * 0.6))
            self.rot("brow." + s, frame, y=sg * R(14 * bt))
            self.rot("lid." + s, frame, x=-R(100 * lid))
        self.expr = name

    def blink(self, frame):
        lid = EXPRESSIONS[self.expr][7]
        for f, k in ((frame, lid), (frame + 2, 1.0), (frame + 3, 1.0), (frame + 6, lid)):
            for s in ("L", "R"):
                self.rot("lid." + s, f, x=-R(118 if k == 1.0 else 100 * k))

    def auto_blinks(self, f0, f1):
        f = f0 + self.rng.randint(8, 30)
        while f < f1 - 8:
            self.blink(f)
            f += self.rng.randint(int(self.fps * 2.2), int(self.fps * 4.5))

    def lipsync(self, f_start, phonemes, base_expr="neutral"):
        """phonemes: [(t0, t1, mnemonic)] in seconds from the line start (eSpeak NG phoneme events)."""
        base = EXPRESSIONS[base_expr]
        smile_base, frown_base = base[0], base[1]
        keyed = 0
        last = f_start
        for t0, t1, ph in phonemes:
            op, wi, ro, cl = viseme(ph)
            fa = f_start + int(round(t0 * self.fps))
            fb = f_start + max(int(round(t1 * self.fps)), int(round(t0 * self.fps)) + 1)
            mid = (fa + fb) // 2
            if mid <= last:
                continue
            self.prop("open", mid, op)
            self.prop("wide", mid, wi)
            self.prop("round", mid, ro)
            self.prop("closed", mid, cl)
            self.prop("smile", mid, smile_base * (1 - 0.5 * op))
            self.prop("frown", mid, frown_base)
            last = mid
            keyed += 1
        end = last + 3
        for k in ("open", "wide", "round", "closed"):
            self.prop(k, end, 0.0)
        self.prop("smile", end, smile_base)
        return keyed


# eSpeak NG phoneme mnemonics -> (open, wide, round, closed)
OPEN_V = ("a", "A", "aI", "aU", "0", "V", "&")
MID_V = ("e", "E", "@", "3", "I", "i", "eI", "e@", "I@", "i:", "3:")
ROUND_V = ("o", "O", "u", "U", "oU", "OI", "u:", "O:", "U@", "w")
BILABIAL = ("m", "b", "p")
LABIODENT = ("f", "v")


def viseme(ph: str):
    p = (ph or "").strip("'\",%=_:;")
    if not p:
        return (0.0, 0.0, 0.0, 0.0)
    if p in BILABIAL:
        return (0.0, 0.0, 0.0, 1.0)
    if p in LABIODENT:
        return (0.12, 0.35, 0.0, 0.3)
    if p.startswith(ROUND_V) or p in ROUND_V:
        return (0.45, 0.0, 0.85, 0.0)
    if p.startswith(OPEN_V):
        return (0.9, 0.35, 0.0, 0.0)
    if p.startswith(MID_V) or p[0] in "eEIi@3":
        return (0.5, 0.45, 0.0, 0.0)
    if p[0] in "tdnlszSZTDrjkgNhx":
        return (0.25, 0.25, 0.0, 0.0)
    return (0.3, 0.2, 0.0, 0.0)


def smooth_keys(rig):
    act = rig.animation_data.action if rig.animation_data else None
    if act:
        for fc in act.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
                kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"


def foot_slide_report(rig, stance_frames: dict) -> dict:
    """Max horizontal movement of each foot (world) across consecutive planted frames, in centimetres."""
    sc = bpy.context.scene
    worst = {}
    for s, frames in stance_frames.items():
        frames = sorted(set(frames))
        prev = None
        mx = 0.0
        for f in frames:
            sc.frame_set(f)
            dg = bpy.context.evaluated_depsgraph_get()
            r = rig.evaluated_get(dg)
            p = r.matrix_world @ r.pose.bones["foot." + s].head
            if prev is not None and prev[0] == f - 1:
                d = (Vector((p.x, p.y, 0)) - Vector((prev[1].x, prev[1].y, 0))).length
                mx = max(mx, d)
            prev = (f, p)
        worst[s] = round(mx * 100, 2)
    return worst
