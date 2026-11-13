"""Build, export, reference-render and deformation-test one character.

Run:  <blender-python> build_character.py -- --char character.json --out characters/<id> [--refs] [--samples 12]

Writes <id>.blend (only the character collection, so scenes can append it), <id>.glb, <id>.fbx (only when the
exporter succeeded), build_report.json, refs/*.png (front, side, back, three-quarter, face, expression sheet frames)
and deform/*.png plus deformation numbers.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import hvanim  # noqa: E402
import hvchar  # noqa: E402
import hvenv  # noqa: E402


def cli():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--char", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--refs", action="store_true")
    p.add_argument("--samples", type=int, default=12)
    return p.parse_args(a)


A = cli()
CHAR = json.load(open(A.char))
CID = CHAR["id"]
OUT = os.path.abspath(A.out)
os.makedirs(OUT, exist_ok=True)

DEFORM_POSES = {
    "rest": {},
    "shoulders_raise": {"upper_arm.L": (0, 0, 80), "upper_arm.R": (0, 0, -80)},
    "arms_forward": {"upper_arm.L": (80, 0, -30), "upper_arm.R": (80, 0, 30)},
    "elbows_bend": {"upper_arm.L": (0, 0, -40), "upper_arm.R": (0, 0, 40), "forearm.L": (110, 0, 0), "forearm.R": (110, 0, 0)},
    "wrists_fingers": {"hand.L": (0, 0, 40), "hand.R": (0, 0, -40), "fingers1.L": (60, 0, 0), "fingers2.L": (70, 0, 0),
                       "fingers1.R": (60, 0, 0), "fingers2.R": (70, 0, 0), "thumb.L": (40, 0, 0), "thumb.R": (40, 0, 0)},
    "hips_twist_bend": {"spine": (20, 15, 0), "chest": (15, 15, 0), "hips": (0, 20, 0)},
    "knees_bend": {"foot_ik.L": "lift", "foot_ik.R": "lift"},
    "head_turn_tilt": {"neck": (10, 25, 0), "head": (10, 30, 12)},
}


def mesh_stats(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    pts = [v.co.copy() for v in me.vertices]
    edges = [tuple(e.vertices) for e in me.edges]
    ev.to_mesh_clear()
    return pts, edges


def deformation_test(rig, body, refs_dir):
    rest_pts, edges = mesh_stats(body)
    rest_len = [(rest_pts[a] - rest_pts[b]).length for a, b in edges]
    results = {}
    H = rig.data.bones["head"].tail_local.z
    for name, pose in DEFORM_POSES.items():
        for pb in rig.pose.bones:
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = (0, 0, 0)
            pb.location = (0, 0, 0)
        for b, v in pose.items():
            if v == "lift":
                rig.pose.bones[b].location = (0, 0, H * 0.18 + rig.data.bones["shin.L"].tail_local.z)
            else:
                rig.pose.bones[b].rotation_euler = tuple(math.radians(x) for x in v)
        bpy.context.view_layer.update()
        pts, _ = mesh_stats(body)
        ratios = [((pts[a] - pts[b]).length / l) if l > 1e-6 else 1.0 for (a, b), l in zip(edges, rest_len)]
        bad = sum(1 for r in ratios if r > 2.5 or r < 0.25)
        finite = all(math.isfinite(c) for p in pts for c in p)
        results[name] = {"max_stretch": round(max(ratios), 3), "min_stretch": round(min(ratios), 3), "edges_over_limit": bad,
                         "edges": len(ratios), "finite": finite,
                         "status": "PASS" if finite and bad <= len(ratios) * 0.002 else "FAIL"}
        if refs_dir:
            bpy.context.scene.render.filepath = os.path.join(refs_dir, f"deform_{name}.png")
            bpy.ops.render.render(write_still=True)
    for pb in rig.pose.bones:
        pb.rotation_euler = (0, 0, 0)
        pb.location = (0, 0, 0)
    return results


def main():
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    res = hvchar.build_character(CHAR)
    rig, coll = res["rig"], res["collection"]
    body = bpy.data.objects[f"{CID}:body"]
    # the collection is named after the character id so scenes can append it
    coll.name = CID
    blend = os.path.join(OUT, CID + ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    exports = []
    glb, fbx = os.path.join(OUT, CID + ".glb"), os.path.join(OUT, CID + ".fbx")
    try:
        bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", export_apply=False, export_skins=True, export_morph=True)
        exports.append("glb")
    except Exception as e:  # noqa: BLE001
        print("GLB_EXPORT_FAILED", e)
    try:
        bpy.ops.export_scene.fbx(filepath=fbx, add_leaf_bones=False, bake_anim=False, use_armature_deform_only=False)
        exports.append("fbx")
    except Exception as e:  # noqa: BLE001
        print("FBX_EXPORT_FAILED", e)
    report = dict(res["report"])
    report["exports"] = exports
    report["blend"] = blend
    report["build_seconds"] = round(time.time() - t0, 1)

    refs = os.path.join(OUT, "refs")
    if A.refs:
        os.makedirs(refs, exist_ok=True)
        env = bpy.data.collections.new("ref_stage")
        sc.collection.children.link(env)
        hvenv.render_settings(sc, 720, 960, A.samples)
        hvenv.world_color(sc, (0.78, 0.82, 0.86, 1), 0.55)
        g = hvenv.plane("ground", env, 30, mat=hvchar.material("refground", "#D9D4C7", 0.95))
        del g
        H = res["joints"]["_H"]
        hvenv.character_lights(env, (0, 0, H * 0.55), key=0.55 * H / 1.2 + 0.25)
        cam = hvenv.camera(sc, env, "refcam", (0, -4, H * 0.55), (0, 0, H * 0.5), lens=50)
        sc.camera = cam
        perf = hvanim.Performer(rig, 24, seed=CID)
        views = {"front": (0, -1), "three_quarter": (0.7, -0.75), "side": (1, 0), "back": (0, 1)}
        dist = H * 2.2 + 0.5
        for name, (dx, dy) in views.items():
            v = Vector((dx, dy, 0)).normalized() * dist
            hvenv.key_camera(cam, 1, (v.x, v.y, H * 0.55), (0, 0, H * 0.5))
            sc.frame_set(1)
            sc.render.filepath = os.path.join(refs, f"{name}.png")
            bpy.ops.render.render(write_still=True)
        # expression sheet: face close-ups
        sc.render.resolution_x = sc.render.resolution_y = 480
        hz = rig.data.bones["head"].head_local.z + res["joints"]["_head_h"] * 0.5
        hvenv.key_camera(cam, 1, (0, -H * 0.45 - 0.35, hz), (0, 0, hz - H * 0.01), lens=70)
        cam.animation_data_clear()
        cam.location = (0, -H * 0.45 - 0.35, hz)
        cam.rotation_euler = (Vector((0, 0, hz)) - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.data.lens = 70
        for i, ex in enumerate(hvanim.EXPRESSIONS):
            f = 10 + i * 10
            perf.expression(f, ex, blend=1)
        for i, ex in enumerate(hvanim.EXPRESSIONS):
            sc.frame_set(10 + i * 10)
            sc.render.filepath = os.path.join(refs, f"expr_{ex}.png")
            bpy.ops.render.render(write_still=True)
        rig.animation_data_clear()
        for pb in rig.pose.bones:
            pb.rotation_euler = (0, 0, 0)
            pb.location = (0, 0, 0)
        pf = rig.pose.bones["face"]
        for k in hvanim.MOUTH_KEYS:
            pf[k] = 0.0
        # deformation test renders (full body, front three-quarter)
        sc.render.resolution_x, sc.render.resolution_y = 480, 640
        cam.location = (H * 1.6, -H * 2.6 - 0.6, H * 0.6)
        cam.rotation_euler = (Vector((0, 0, H * 0.5)) - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.data.lens = 45
        sc.frame_set(1)
    report["deformation"] = deformation_test(rig, body, refs if A.refs else None)
    report["deformation_status"] = "PASS" if all(r["status"] == "PASS" for r in report["deformation"].values()) else "FAIL"
    with open(os.path.join(OUT, "build_report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("CHARACTER_OK", CID, json.dumps({k: report[k] for k in ("vertices", "bones", "exports", "deformation_status")}))


main()
