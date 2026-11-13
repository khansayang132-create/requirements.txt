"""HUMANVERSE environments, props, lighting and cameras (Blender)."""

from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector

from hvchar import material, sphere


def _obj(name, me, coll):
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    return o


def plane(name, coll, size, loc=(0, 0, 0), mat=None, rot=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size / 2)
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, coll)
    o.location, o.rotation_euler = loc, rot
    if mat:
        me.materials.append(mat)
    return o


def box(name, coll, size, loc, mat, bevel=0.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, coll)
    o.location = loc
    me.materials.append(mat)
    if bevel:
        m = o.modifiers.new("bevel", "BEVEL")
        m.width, m.segments = bevel, 3
    return o


def cylinder(name, coll, r, depth, loc, mat, verts=24, r2=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r, radius2=r if r2 is None else r2, depth=depth)
    bm.to_mesh(me)
    bm.free()
    o = _obj(name, me, coll)
    o.location = loc
    me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    return o


def tree(coll, loc, h, rng, mats):
    x, y = loc
    cylinder("trunk", coll, h * 0.06, h * 0.55, (x, y, h * 0.27), mats["bark"], r2=h * 0.045)
    for k in range(5):
        a = rng.random() * 6.28
        r = h * (0.22 + 0.08 * rng.random())
        sphere("leaves", coll, (x + math.cos(a) * h * 0.14, y + math.sin(a) * h * 0.14, h * (0.62 + 0.18 * rng.random())), (r, r, r * 0.9),
               seg=20, rings=12, mat=mats["leaf" if k % 2 else "leaf2"])


def world_sky(scene, sun_elev=35, sun_rot=40, strength=0.35):
    w = scene.world or bpy.data.worlds.new("world")
    scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(sun_elev)
    sky.sun_rotation = math.radians(sun_rot)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs[1].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(sky.outputs[0], bg.inputs[0])
    nt.links.new(bg.outputs[0], out.inputs[0])


def world_color(scene, color, strength):
    w = scene.world or bpy.data.worlds.new("world")
    scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background") or w.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs[0].default_value = color
    bg.inputs[1].default_value = strength


def light(coll, kind, loc, target, energy, size=1.0, color=(1, 1, 1), name="light"):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == "AREA":
        ld.size = size
    if kind == "SUN":
        ld.angle = math.radians(3)
    o = _obj(name, ld, coll)
    o.location = loc
    d = Vector(target) - Vector(loc)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return o


def env_park(scene, coll, seed=1, time_of_day="day"):
    rng = random.Random(seed)
    mats = {"grass": material("grass", "#7DAE5A", 0.95), "path": material("path", "#D9C49A", 0.9), "bark": material("bark", "#6B4A32", 0.9),
            "leaf": material("leaf", "#4E8F3E", 0.8), "leaf2": material("leaf2", "#6AA84F", 0.8), "wood": material("wood", "#A0683C", 0.6),
            "metal": material("metal", "#3B3F45", 0.35), "flower": material("flower", "#F2C14E", 0.6), "flower2": material("flower2", "#E46F8C", 0.6)}
    plane("ground", coll, 80, mat=mats["grass"])
    p = plane("path", coll, 1, loc=(0, 1.2, 0.003), mat=mats["path"])
    p.scale = (30, 1.6, 1)
    for x, y, h in ((-6, 7, 5.5), (5, 9, 6.2), (-11, 14, 7), (11, 15, 6.5), (0, 18, 6), (-3.5, 11, 4.6), (8, 5, 4.8), (-9, 4, 4.4)):
        tree(coll, (x, y), h, rng, mats)
    # bench
    box("bench_seat", coll, (1.6, 0.42, 0.06), (2.6, 2.6, 0.45), mats["wood"], 0.01)
    box("bench_back", coll, (1.6, 0.06, 0.38), (2.6, 2.82, 0.78), mats["wood"], 0.01)
    for dx in (-0.7, 0.7):
        box("bench_leg", coll, (0.06, 0.42, 0.45), (2.6 + dx, 2.6, 0.22), mats["metal"])
    for _ in range(40):
        x, y = rng.uniform(-9, 9), rng.uniform(3.5, 12)
        sphere("flower", coll, (x, y, 0.05), (0.06, 0.06, 0.05), seg=8, rings=6, mat=mats["flower" if rng.random() < 0.5 else "flower2"])
    if time_of_day == "sunset":
        world_sky(scene, 6, 200, 0.45)
        light(coll, "SUN", (5, -8, 3), (0, 0, 0.8), 2.6, color=(1.0, 0.72, 0.5), name="sun")
    else:
        world_sky(scene, 38, 150, 0.3)
        light(coll, "SUN", (6, -6, 9), (0, 0, 0.8), 3.2, color=(1.0, 0.95, 0.88), name="sun")


def env_room(scene, coll, seed=2):
    mats = {"floor": material("floor", "#B9875A", 0.5), "wall": material("wall", "#EADFCB", 0.9), "wall2": material("wall2", "#9EC2C9", 0.9),
            "sofa": material("sofa", "#C8553D", 0.85), "rug": material("rug", "#3D6B8E", 0.95), "wood": material("wood2", "#7A4E2D", 0.5),
            "lamp": material("lampshade", "#FFE9B8", 0.6, emit=2.0), "window": material("window", "#CFE8FF", 0.1, emit=1.5),
            "plant": material("plant", "#4E8F3E", 0.8), "pot": material("pot", "#D97B4A", 0.7)}
    plane("floor", coll, 14, mat=mats["floor"])
    plane("rug", coll, 1, loc=(0, 0.6, 0.004), mat=mats["rug"]).scale = (3.2, 2.2, 1)
    plane("wall_back", coll, 14, loc=(0, 3.6, 3), rot=(math.radians(90), 0, 0), mat=mats["wall"])
    plane("wall_left", coll, 14, loc=(-4.2, 0, 3), rot=(math.radians(90), 0, math.radians(90)), mat=mats["wall2"])
    plane("window", coll, 1, loc=(-1.6, 3.58, 1.7), rot=(math.radians(90), 0, 0), mat=mats["window"]).scale = (1.6, 1.2, 1)
    box("sofa_base", coll, (2.2, 0.85, 0.42), (1.3, 2.9, 0.25), mats["sofa"], 0.06)
    box("sofa_back", coll, (2.2, 0.25, 0.55), (1.3, 3.25, 0.7), mats["sofa"], 0.06)
    for dx in (-1.05, 1.05):
        box("sofa_arm", coll, (0.22, 0.85, 0.55), (1.3 + dx, 2.9, 0.4), mats["sofa"], 0.05)
    box("table", coll, (1.0, 0.55, 0.05), (-1.6, 1.6, 0.48), mats["wood"], 0.01)
    for dx, dy in ((-0.42, -0.2), (0.42, -0.2), (-0.42, 0.2), (0.42, 0.2)):
        box("table_leg", coll, (0.05, 0.05, 0.46), (-1.6 + dx, 1.6 + dy, 0.23), mats["wood"])
    cylinder("lamp_pole", coll, 0.025, 1.5, (3.0, 3.1, 0.75), mats["wood"])
    cylinder("lamp_shade", coll, 0.25, 0.32, (3.0, 3.1, 1.6), mats["lamp"], r2=0.17)
    cylinder("pot", coll, 0.18, 0.35, (-3.4, 3.0, 0.17), mats["pot"], r2=0.22)
    sphere("plant", coll, (-3.4, 3.0, 0.75), (0.38, 0.38, 0.5), mat=mats["plant"])
    world_color(scene, (0.85, 0.9, 1.0, 1), 0.25)
    light(coll, "AREA", (-1.6, 2.6, 2.2), (0, 0, 1.0), 260, size=2.0, color=(0.85, 0.92, 1.0), name="window_light")
    light(coll, "POINT", (3.0, 3.0, 1.6), (0, 0, 1), 60, color=(1.0, 0.8, 0.55), name="lamp_light")


def env_street(scene, coll, seed=3):
    rng = random.Random(seed)
    mats = {"road": material("road", "#4A4E57", 0.85), "walk": material("sidewalk", "#BDB5A6", 0.9), "roof": material("roof", "#9C4A3B", 0.7),
            "win": material("win", "#FFD98A", 0.3, emit=1.2), "door": material("door", "#4E5D6C", 0.6)}
    plane("road", coll, 60, mat=mats["road"])
    plane("sidewalk", coll, 1, loc=(0, 3.0, 0.06), mat=mats["walk"]).scale = (60, 4, 1)
    walls = ["#E8C07D", "#9FC5C2", "#E7A38E", "#C9B6E4", "#F0E2B6"]
    for i, x in enumerate(range(-12, 13, 5)):
        h = rng.uniform(3.2, 5.2)
        wm = material("house%d" % i, walls[i % len(walls)], 0.85)
        box("house", coll, (4.4, 4, h), (x, 7.2, h / 2), wm)
        box("roof", coll, (4.6, 4.2, 0.3), (x, 7.2, h + 0.15), mats["roof"])
        box("door", coll, (0.9, 0.05, 1.9), (x - 0.8, 5.18, 0.95), mats["door"])
        box("window", coll, (1.1, 0.05, 0.9), (x + 1.0, 5.18, 1.9), mats["win"])
    world_sky(scene, 4, 210, 0.55)
    light(coll, "SUN", (-6, -6, 3), (0, 0, 0.8), 2.4, color=(1.0, 0.68, 0.45), name="sun")


ENVIRONMENTS = {"park": env_park, "park_sunset": lambda s, c, seed=1: env_park(s, c, seed, "sunset"), "room": env_room, "street": env_street}


def character_lights(coll, center=(0, 0, 0.9), key=1.0):
    """Cinematic three-point rig around the action: warm key, cool fill, rim for silhouette separation."""
    cx, cy, cz = center
    light(coll, "AREA", (cx + 2.6, cy - 3.2, cz + 2.0), (cx, cy, cz), 260 * key, size=2.5, color=(1.0, 0.93, 0.85), name="key")
    light(coll, "AREA", (cx - 3.2, cy - 2.2, cz + 0.8), (cx, cy, cz), 90 * key, size=3.0, color=(0.82, 0.9, 1.0), name="fill")
    light(coll, "AREA", (cx - 0.8, cy + 3.0, cz + 2.0), (cx, cy, cz + 0.4), 220 * key, size=1.5, color=(0.75, 0.9, 1.0), name="rim")


def camera(scene, coll, name, loc, target, lens=40, dof_target=None, fstop=2.8):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36
    o = _obj(name, cd, coll)
    o.location = loc
    d = Vector(target) - Vector(loc)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    if dof_target is not None:
        cd.dof.use_dof = True
        cd.dof.focus_distance = (Vector(dof_target) - Vector(loc)).length
        cd.dof.aperture_fstop = fstop
    return o


def key_camera(cam, frame, loc, target, lens=None):
    cam.location = loc
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.keyframe_insert("location", frame=frame)
    cam.keyframe_insert("rotation_euler", frame=frame)
    if lens:
        cam.data.lens = lens
        cam.data.keyframe_insert("lens", frame=frame)


def render_settings(scene, w, h, samples=16, fps=24):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 6
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 2
    scene.cycles.transmission_bounces = 2
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "AgX"
    try:
        scene.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    scene.render.use_persistent_data = True
    scene.view_settings.exposure = -0.7
    scene.cycles.adaptive_threshold = 0.04
