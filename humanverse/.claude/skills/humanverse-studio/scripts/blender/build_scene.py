"""Build one animated scene from a scene spec (JSON) and save it as a .blend.

Run:  <blender-python> build_scene.py -- --spec scene.json --lines lines.json --out scene.blend --report report.json

Characters are appended from their approved character .blend files (never rebuilt), so a character cannot change
between scenes. Every action in the spec becomes keyframes on that character's rig; dialogue drives lip sync from
the eSpeak phoneme timings; each shot gets its own camera bound to a timeline marker.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import hvanim  # noqa: E402
import hvenv  # noqa: E402
from hvchar import material, sphere  # noqa: E402


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--spec", required=True)
    p.add_argument("--lines", default="")
    p.add_argument("--out", required=True)
    p.add_argument("--report", required=True)
    return p.parse_args(a)


def append_character(path, cid):
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.collections = [c for c in src.collections if c == cid]
    coll = dst.collections[0]
    bpy.context.scene.collection.children.link(coll)
    rig = next(o for o in coll.objects if o.type == "ARMATURE")
    return rig, coll


def add_tears(rig, coll, f0, f1, fps):
    H = rig.data.bones["head"].tail_local.z
    mat = material("tear", "#9FD8FF", 0.05, coat=1.0)
    objs = []
    for s in ("L", "R"):
        eye = rig.data.bones["eye." + s].head_local
        for k in range(3):
            t = sphere(f"{rig.name}:tear.{s}{k}", coll, (0, 0, 0), (H * 0.006, H * 0.006, H * 0.009), seg=12, rings=8, mat=mat)
            t.parent = rig
            t.parent_type = "BONE"
            t.parent_bone = "head"
            start = rig.matrix_world @ (eye + Vector((-0.4 * (1 if s == "L" else -1) * H * 0.012, -H * 0.03, -H * 0.012)))
            t.matrix_world.translation = start
            base = t.location.copy()
            period = int(fps * 1.1)
            first = f0 + k * period // 3
            t.scale = (0, 0, 0)
            t.keyframe_insert("scale", frame=f0)
            f = first
            while f < f1:
                t.location = base
                t.scale = (0, 0, 0)
                t.keyframe_insert("location", frame=f)
                t.keyframe_insert("scale", frame=f)
                t.scale = (1, 1, 1)
                t.keyframe_insert("scale", frame=f + 3)
                t.location = base + Vector((0, -H * 0.075, -H * 0.004))      # head bone: -Y is down the cheek
                t.keyframe_insert("location", frame=f + period)
                t.scale = (0.6, 0.6, 0.6)
                t.keyframe_insert("scale", frame=f + period - 1)
                t.scale = (0, 0, 0)
                t.keyframe_insert("scale", frame=f + period)
                f += period
            objs.append(t)
    return len(objs)


def kite(coll, color="#E4573D"):
    from hvenv import _obj
    import bmesh
    me = bpy.data.meshes.new("kite")
    bm = bmesh.new()
    vs = [bm.verts.new(v) for v in ((0, 0, 0.45), (0.3, 0, 0.05), (0, 0, -0.35), (-0.3, 0, 0.05))]
    bm.faces.new(vs)
    bm.to_mesh(me)
    bm.free()
    o = _obj("kite", me, coll)
    m = o.modifiers.new("solid", "SOLIDIFY")
    m.thickness = 0.01
    me.materials.append(material("kite", color, 0.5))
    tail = sphere("kite_tail", coll, (0, 0, -0.55), (0.04, 0.02, 0.18), mat=material("kite_tail", "#F2C14E", 0.6))
    tail.parent = o
    return o


def palm_world(rig, side: str):
    """World position of the palm: midpoint of the hand bone (wrist to hand end)."""
    pb = rig.pose.bones["hand." + side]
    return (rig.matrix_world @ ((pb.head + pb.tail) * 0.5))


def bake_attach(sc, obj, segments: list[dict], rigs: dict) -> None:
    """Key `obj` to a character's palm (+ offset) on every frame of each segment: {f0, f1, char, hand, offset}.
    Location keys inside a segment are replaced; rotation keys from the spec are kept."""
    if obj is None or not segments:
        return
    for seg in segments:
        fc = obj.animation_data.action.fcurves if obj.animation_data and obj.animation_data.action else []
        for c in fc:
            if c.data_path == "location":
                for kp in [k for k in c.keyframe_points if seg["f0"] <= k.co[0] <= seg["f1"]][::-1]:
                    c.keyframe_points.remove(kp)
        off = seg.get("offset", [0, 0, 0])
        for f in range(seg["f0"], seg["f1"] + 1):
            sc.frame_set(f)
            pw = palm_world(rigs[seg["char"]], seg.get("hand", "R"))
            obj.location = (pw.x + off[0], pw.y + off[1], pw.z + off[2])
            obj.keyframe_insert("location", frame=f)
    sc.frame_set(1)


def main():
    A = args()
    spec = json.load(open(A.spec))
    lines = {ln["line_id"]: ln for ln in json.load(open(A.lines))} if A.lines and os.path.exists(A.lines) else {}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    fps = spec.get("fps", 24)
    w, h = spec.get("resolution", [1280, 720])
    hvenv.render_settings(sc, w, h, spec.get("samples", 16), fps)
    sc.frame_start, sc.frame_end = 1, spec["frames"]
    env_coll = bpy.data.collections.new("environment")
    sc.collection.children.link(env_coll)
    hvenv.ENVIRONMENTS[spec["environment"]](sc, env_coll, spec.get("seed", 1))
    center = spec.get("light_center", [0, 0, 0.9])
    hvenv.character_lights(env_coll, center, spec.get("key", 1.0) * (1.0 if spec["environment"] == "room" else 0.5))

    perf, rigs, colls = {}, {}, {}
    for c in spec["characters"]:
        rig, coll = append_character(c["blend"], c["id"])
        rigs[c["id"]], colls[c["id"]] = rig, coll
        p = hvanim.Performer(rig, fps, seed=spec["scene_id"] + c["id"])
        x, y, hd = c["start"]
        p.place(1, x, y, hd)
        p.stand(1)
        p.expression(1, c.get("expression", "neutral"), blend=1)
        perf[c["id"]] = p

    cues, tears = [], 0
    props = {}
    for pr in spec.get("props", []):
        if pr["type"] == "kite":
            k = kite(env_coll)
            props[pr.get("name", "kite")] = k
            for key in pr.get("keys", []):
                k.location = key["loc"]
                k.rotation_euler = [math.radians(v) for v in key.get("rot", [0, 0, 0])]
                k.keyframe_insert("location", frame=key["f"])
                k.keyframe_insert("rotation_euler", frame=key["f"])

    for ev in spec["performance"]:
        p = perf[ev["char"]]
        op = ev["op"]
        if op == "walk":
            end = p.walk(ev["f"], ev["path"], ev.get("speed"))
            p.stand(end + 4)
            if "heading" in ev:
                p.turn_to(end, end + 8, ev["heading"])
        elif op == "turn":
            p.turn_to(ev["f0"], ev["f1"], ev["heading"])
        elif op == "stand":
            p.stand(ev["f"])
        elif op == "idle":
            p.idle(ev["f0"], ev["f1"], ev.get("energy", 1.0))
        elif op == "expression":
            p.expression(ev["f"], ev["name"], ev.get("blend", 6))
        elif op == "say":
            ln = lines[ev["line_id"]]
            n = p.lipsync(ev["f"], [tuple(x) for x in ln["phonemes"]], ev.get("base", p.expr))
            cues.append({"type": "dialogue", "line_id": ev["line_id"], "frame": ev["f"], "char": ev["char"], "wav": ln["wav"],
                         "visemes_keyed": n, "duration": ln["duration"]})
            if ev.get("gesture", True):
                end = ev["f"] + int(ln["duration"] * fps)
                p.gesture_talk(ev["f"], max(ev["f"] + 12, end), ev.get("hand", "L"), ev.get("amount", 0.8))
        elif op == "wave":
            p.wave(ev["f0"], ev["f1"], ev.get("side", "R"))
        elif op == "cheer":
            p.cheer(ev["f0"], ev["f1"])
        elif op == "hug_self":
            p.hug_self(ev["f0"], ev["f1"])
        elif op == "reach":
            p.reach(ev["f0"], ev["f1"], ev.get("side", "R"), ev.get("fwd", 60), ev.get("raise", 20))
        elif op == "nod":
            p.nod(ev["f"], ev.get("times", 2))
        elif op == "slump":
            p.slump(ev["f0"], ev["f1"], ev.get("amount", 1.0))
        elif op == "look":
            p.look(ev["f"], ev.get("yaw", 0), ev.get("pitch", 0), ev.get("head", True))
        elif op == "cry":
            p.expression(ev["f0"], "crying")
            tears += add_tears(rigs[ev["char"]], colls[ev["char"]], ev["f0"], ev["f1"], fps)
        elif op == "blinks":
            p.auto_blinks(ev["f0"], ev["f1"])
        else:
            raise ValueError("unknown op " + op)

    for cid, p in perf.items():
        p.auto_blinks(1, spec["frames"]) if not any(e["op"] == "blinks" and e["char"] == cid for e in spec["performance"]) else None
        hvanim.smooth_keys(p.rig)
        for s, frames in p.stance_frames.items():
            fs = sorted(set(frames))
            for i, f in enumerate(fs):
                if i == 0 or fs[i - 1] != f - 1:
                    cues.append({"type": "footstep", "frame": f, "char": cid, "side": s})

    # props held in a hand: baked to the hand bone on every frame of each segment, after all body animation is keyed,
    # so the prop follows the hand exactly. Between two segments the keys interpolate: that is the hand-off.
    for pr in spec.get("props", []):
        bake_attach(sc, props.get(pr.get("name", "kite")), pr.get("attach", []), rigs)

    # cameras: one per shot, bound with timeline markers
    shots = []
    for i, sh in enumerate(spec["shots"]):
        c = sh["cam"]
        cam = hvenv.camera(sc, env_coll, "CAM_" + sh["shot_id"], c["loc"], c["target"], c.get("lens", 40), c.get("focus"), c.get("fstop", 2.8))
        if "end" in sh:
            e = sh["end"]
            hvenv.key_camera(cam, sh["f0"], c["loc"], c["target"], c.get("lens"))
            hvenv.key_camera(cam, sh["f1"], e["loc"], e["target"], e.get("lens"))
            if cam.animation_data and cam.animation_data.action:
                for fc in cam.animation_data.action.fcurves:
                    for kp in fc.keyframe_points:
                        kp.interpolation = "BEZIER"
        m = sc.timeline_markers.new(sh["shot_id"], frame=sh["f0"])
        m.camera = cam
        if i == 0:
            sc.camera = cam
        shots.append({"shot_id": sh["shot_id"], "f0": sh["f0"], "f1": sh["f1"], "camera": cam.name})

    slides = {cid: hvanim.foot_slide_report(p.rig, p.stance_frames) for cid, p in perf.items() if any(p.stance_frames.values())}
    sc.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(A.out))
    rep = {"scene_id": spec["scene_id"], "blend": os.path.abspath(A.out), "frames": spec["frames"], "fps": fps, "resolution": [w, h],
           "characters": list(rigs), "shots": shots, "cues": cues, "tears": tears, "foot_slide_cm": slides,
           "actions": {cid: len(r.animation_data.action.fcurves) for cid, r in rigs.items()}}
    with open(A.report, "w") as f:
        json.dump(rep, f, indent=2)
    print("SCENE_OK", json.dumps({k: rep[k] for k in ("scene_id", "frames", "tears", "foot_slide_cm")}))


if __name__ == "__main__":
    main()
