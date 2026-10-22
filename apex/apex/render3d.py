"""Procedural 3D scene renderer (Blender / Cycles).

Run in a Python that has `bpy` installed:
    python -m apex.render3d scene.json out_dir --fps 24 --width 432 --height 768 --samples 8

Writes out_dir/frame_0001.png ... and out_dir/render_info.json. Every frame is a real
Cycles path-traced render of a procedurally built scene; nothing here is AI-generated.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import bpy  # noqa: E402  (only importable inside a bpy-enabled Python)

GOLD = (1.0, 0.70, 0.28, 1)
COFFEE = (0.10, 0.045, 0.02, 1)
CERAMIC = (0.92, 0.90, 0.86, 1)
PIG = (0.95, 0.52, 0.62, 1)
RED = (0.85, 0.08, 0.12, 1)
FLOOR = (0.035, 0.04, 0.05, 1)


def material(name, color, metallic=0.0, roughness=0.35):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return m


def assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def add(op, **kw):
    getattr(bpy.ops.mesh, op)(**kw)
    return bpy.context.active_object


def bevel(obj, width=0.02, segments=3):
    mod = obj.modifiers.new("bevel", "BEVEL")
    mod.width, mod.segments = width, segments
    bpy.ops.object.shade_smooth()
    return obj


def key(obj, frame, **props):
    for attr, value in props.items():
        setattr(obj, attr, value)
        obj.keyframe_insert(data_path=attr, frame=frame)


def coin(mat, location, upright=False, radius=0.32):
    c = add("primitive_cylinder_add", radius=radius, depth=radius * 0.18, vertices=48, location=location)
    if upright:
        c.rotation_euler = (math.radians(90), 0, 0)
    bevel(c, width=radius * 0.03)
    return assign(c, mat)


# ---------------------------------------------------------------- stage

def build_stage(width, height, samples):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 6
    sc.render.resolution_x, sc.render.resolution_y = width, height
    sc.render.resolution_percentage = 100
    sc.render.use_persistent_data = True
    sc.render.image_settings.file_format = "PNG"

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.012, 0.016, 0.03, 1)
    bg.inputs["Strength"].default_value = 1.0
    sc.world = world

    floor = add("primitive_plane_add", size=60, location=(0, 0, 0))
    assign(floor, material("floor", FLOOR, roughness=0.28))

    def area(name, loc, energy, color, size):
        light = bpy.data.lights.new(name, "AREA")
        light.energy, light.color, light.size = energy, color, size
        obj = bpy.data.objects.new(name, light)
        obj.location = loc
        sc.collection.objects.link(obj)
        tc = obj.constraints.new("TRACK_TO")
        tc.target = target
        return obj

    target = bpy.data.objects.new("target", None)
    target.location = (0, 0, 1.0)
    sc.collection.objects.link(target)
    area("key", (3.5, -3.5, 5.0), 900, (1.0, 0.88, 0.72), 3.0)
    area("rim", (-4.0, 3.5, 3.5), 1200, (0.55, 0.7, 1.0), 2.0)
    area("fill", (-3.0, -4.5, 1.5), 120, (1.0, 1.0, 1.0), 4.0)

    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 40
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = target
    cam_data.dof.aperture_fstop = 2.8
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    tc = cam.constraints.new("TRACK_TO")
    tc.target = target
    sc.camera = cam
    return sc, cam, target


def camera_path(cam, move, frames, distance=7.0, height=1.8):
    """Keyframe the camera around the target according to the named move."""
    def place(frame, dist, angle_deg, z):
        a = math.radians(angle_deg)
        key(cam, frame, location=(dist * math.sin(a), -dist * math.cos(a), z))

    start, end = 1, frames
    moves = {
        "static": ((distance, 0, height), (distance, 0, height)),
        "dolly_in": ((distance * 1.25, 0, height), (distance * 0.85, 0, height * 0.9)),
        "dolly_out": ((distance * 0.85, 0, height * 0.9), (distance * 1.25, 0, height)),
        "orbit_left": ((distance, 18, height), (distance, -18, height)),
        "orbit_right": ((distance, -18, height), (distance, 18, height)),
        "crane_up": ((distance, 0, 0.9), (distance * 1.05, 0, 4.2)),
    }
    (d0, a0, z0), (d1, a1, z1) = moves[move]
    place(start, d0, a0, z0)
    place(end, d1, a1, z1)
    if cam.animation_data and cam.animation_data.action:
        _ease(cam.animation_data.action)


def _ease(action):
    """Smooth starts and stops on every keyframe (Blender 4.4+ layered actions and older ones)."""
    curves = []
    if hasattr(action, "fcurves"):
        try:
            curves = list(action.fcurves)
        except Exception:  # noqa: BLE001
            curves = []
    if not curves and hasattr(action, "layers"):
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    curves.extend(bag.fcurves)
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.easing = "EASE_IN_OUT"


# ---------------------------------------------------------------- templates

def t_hero_coin(frames, params):
    gold = material("gold", GOLD, metallic=1.0, roughness=0.22)
    c = coin(gold, (0, 0, 1.25), upright=True, radius=1.0)
    key(c, 1, rotation_euler=(math.radians(90), 0, math.radians(-35)))
    key(c, frames, rotation_euler=(math.radians(90), 0, math.radians(325)))
    for i, (x, y) in enumerate([(-1.6, 0.8), (1.5, 0.6), (-0.9, -0.7), (1.1, -0.9)]):
        coin(gold, (x, y, 0.03), radius=0.32)


def t_coffee_cup(frames, params):
    ceramic = material("ceramic", CERAMIC, roughness=0.18)
    coffee = material("coffee", COFFEE, roughness=0.08)
    gold = material("gold", GOLD, metallic=1.0, roughness=0.22)
    saucer = add("primitive_cylinder_add", radius=1.25, depth=0.08, vertices=64, location=(0, 0, 0.04))
    bevel(assign(saucer, ceramic), 0.03)
    cup = add("primitive_cylinder_add", radius=0.7, depth=1.2, vertices=64, location=(0, 0, 0.68))
    bevel(assign(cup, ceramic), 0.04)
    liquid = add("primitive_cylinder_add", radius=0.64, depth=0.02, vertices=64, location=(0, 0, 1.285))
    assign(liquid, coffee)
    handle = add("primitive_torus_add", major_radius=0.33, minor_radius=0.07, location=(0.82, 0, 0.72),
                 rotation=(math.radians(90), 0, 0))
    bpy.ops.object.shade_smooth()
    assign(handle, ceramic)
    # Coins rise out of the cup one after another: money leaving with every cup.
    n = int(params.get("coins", 6))
    for i in range(n):
        c = coin(gold, (0, 0, 1.0), radius=0.22)
        t0 = 1 + int(i * frames / (n + 1))
        t1 = min(frames, t0 + int(frames * 0.45))
        ang = math.radians(i * 360 / n)
        key(c, t0, location=(0, 0, 1.0), scale=(0.01, 0.01, 0.01))
        key(c, t0 + 2, location=(0, 0, 1.3), scale=(1, 1, 1))
        key(c, t1, location=(1.6 * math.cos(ang), 1.6 * math.sin(ang), 2.6 + 0.2 * i), scale=(1, 1, 1),
            rotation_euler=(math.radians(70), math.radians(30 * i), 0))


def t_coin_stack(frames, params):
    gold = material("gold", GOLD, metallic=1.0, roughness=0.22)
    stacks = [max(1, min(12, int(h))) for h in params.get("stacks", [3, 6, 9])][:5]
    spacing = 1.15
    x0 = -spacing * (len(stacks) - 1) / 2
    total = sum(stacks)
    n = 0
    for si, h in enumerate(stacks):
        for k in range(h):
            c = coin(gold, (x0 + si * spacing, 0, 0.05 + k * 0.1), radius=0.48)
            appear = 1 + int(n * (frames * 0.75) / total)
            key(c, max(1, appear - 1), scale=(0.001, 0.001, 0.001))
            key(c, appear + 2, scale=(1, 1, 1))
            n += 1


def t_bar_chart(frames, params):
    gold = material("gold", GOLD, metallic=1.0, roughness=0.25)
    red = material("red", RED, metallic=0.3, roughness=0.3)
    values = [max(0.1, float(v)) for v in params.get("values", [1, 2, 3, 4, 5, 6])][:12]
    top = max(values)
    spacing = 2.6 / max(1, len(values) - 1) if len(values) > 1 else 0
    x0 = -1.3 if len(values) > 1 else 0
    for i, v in enumerate(values):
        hgt = 2.4 * v / top
        bar = add("primitive_cube_add", size=1, location=(x0 + i * spacing, 0, 0))
        bar.scale = (0.26, 0.26, 0.001)
        bevel(assign(bar, red if i == len(values) - 1 else gold), 0.02, 2)
        grow_start = 1 + int(i * frames * 0.5 / len(values))
        key(bar, grow_start, scale=(0.26, 0.26, 0.001), location=(bar.location.x, 0, 0))
        key(bar, min(frames, grow_start + int(frames * 0.35)), scale=(0.26, 0.26, hgt),
            location=(bar.location.x, 0, hgt / 2))


def t_piggy_bank(frames, params):
    pink = material("pig", PIG, roughness=0.32)
    gold = material("gold", GOLD, metallic=1.0, roughness=0.22)
    dark = material("dark", (0.02, 0.02, 0.02, 1), roughness=0.4)
    body = add("primitive_uv_sphere_add", radius=1.0, segments=48, ring_count=24, location=(0, 0, 1.15))
    body.scale = (1.25, 0.95, 0.92)
    bpy.ops.object.shade_smooth()
    assign(body, pink)
    snout = add("primitive_cylinder_add", radius=0.32, depth=0.3, vertices=32, location=(-1.32, 0, 1.15),
                rotation=(0, math.radians(90), 0))
    bevel(assign(snout, pink), 0.05)
    for y in (-0.5, 0.5):
        ear = add("primitive_cone_add", radius1=0.22, depth=0.35, location=(-0.75, y, 1.95))
        assign(ear, pink)
        for x in (-0.6, 0.6):
            leg = add("primitive_cylinder_add", radius=0.17, depth=0.5, location=(x, y, 0.25))
            bevel(assign(leg, pink), 0.04)
        eye = add("primitive_uv_sphere_add", radius=0.07, location=(-1.12, y * 0.6, 1.5))
        assign(eye, dark)
    slot = add("primitive_cube_add", size=1, location=(0, 0, 2.02))
    slot.scale = (0.45, 0.06, 0.03)
    assign(slot, dark)
    n = max(0, min(20, int(params.get("coins", 5))))
    for i in range(n):
        c = coin(gold, (0, 0, 5.0), upright=True, radius=0.2)
        c.rotation_euler = (math.radians(90), 0, math.radians(90))
        t0 = 1 + int(i * frames * 0.8 / max(1, n))
        t1 = min(frames, t0 + max(4, int(frames * 0.12)))
        key(c, t0, location=(0, 0, 4.6))
        key(c, t1, location=(0, 0, 1.95))
        key(c, t1 + 1, scale=(1, 1, 1))
        key(c, min(frames, t1 + 2), scale=(0.001, 0.001, 0.001))


TEMPLATES = {"hero_coin": t_hero_coin, "coffee_cup": t_coffee_cup, "coin_stack": t_coin_stack,
             "bar_chart": t_bar_chart, "piggy_bank": t_piggy_bank}


def render_scene(scene: dict, out_dir: Path, fps: int, width: int, height: int, samples: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = max(1, round(scene["duration"] * fps))
    sc, cam, _target = build_stage(width, height, samples)
    sc.render.fps = fps
    sc.frame_start, sc.frame_end = 1, frames
    TEMPLATES[scene["template"]](frames, scene.get("params", {}))
    camera_path(cam, scene["camera_move"], frames)
    sc.render.filepath = str(out_dir / "frame_")
    t = time.time()
    bpy.ops.render.render(animation=True)
    info = {"scene_id": scene["scene_id"], "template": scene["template"], "frames": frames, "fps": fps,
            "width": width, "height": height, "samples": samples, "engine": "CYCLES (CPU)",
            "blender": bpy.app.version_string, "render_seconds": round(time.time() - t, 1)}
    (out_dir / "render_info.json").write_text(json.dumps(info, indent=2))
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene_json")
    ap.add_argument("out_dir")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--width", type=int, default=432)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--samples", type=int, default=8)
    a = ap.parse_args()
    scene = json.loads(Path(a.scene_json).read_text())
    print(json.dumps(render_scene(scene, Path(a.out_dir), a.fps, a.width, a.height, a.samples)))


if __name__ == "__main__":
    main()
