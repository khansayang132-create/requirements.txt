"""HUMANVERSE character engine (runs inside Blender: `blender --background --python` or the `bpy` module).

Builds an original stylized 3D human from a character's appearance.json, deterministically:

  body      one watertight skin-modifier mesh (neck, torso, arms, hands with 4 fingers + thumb, legs, feet),
            subdivided, automatically weighted to the deform skeleton (bone heat), measured, with a
            deterministic fallback if heat weighting leaves vertices unweighted or leaks across sides
  head      shaped ellipsoid with nose and ears; eyes (white, iris, pupil, highlight) on eye bones;
            upper eyelids on lid bones (blink); brows on brow bones; a mouth whose shape keys
            (open, smile, frown, wide, round, closed-M) are driven from face controls on the head
  hair      hairline-cut cap + style pieces (bun, ponytail, curls, spikes, side-fringe, balding), optional beard
  clothes   shirt/sleeves and trousers as their own skin meshes, weighted to the same skeleton; shoes
  rig       root, hips, spine, chest, neck, head, clavicles, arms, hands, finger and thumb chains, legs, feet,
            toes; leg IK (foot_ik + knee pole) and arm IK targets (off by default, FK animation); face bones

Rest pose is an A-pose. Every limb bone's Z axis points forward (-Y), so a positive X rotation always swings the
bone forward; animation code relies on that convention.
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

FWD = Vector((0, -1, 0))


# ----------------------------------------------------------------------------------------------- helpers
def hexcol(h: str, a: float = 1.0):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return (*lin, a)


def material(name: str, color: str, rough: float = 0.55, sss: float = 0.0, spec: float = 0.4, emit: float = 0.0, coat: float = 0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = hexcol(color)
    b.inputs["Roughness"].default_value = rough
    if "Specular IOR Level" in b.inputs:
        b.inputs["Specular IOR Level"].default_value = spec
    if sss > 0 and "Subsurface Weight" in b.inputs:
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.2)
        b.inputs["Subsurface Scale"].default_value = 0.02
    if emit > 0:
        b.inputs["Emission Color"].default_value = hexcol(color)
        b.inputs["Emission Strength"].default_value = emit
    if coat > 0 and "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = coat
    m.diffuse_color = hexcol(color)
    return m


def link(obj, coll):
    coll.objects.link(obj)
    return obj


def new_mesh_obj(name, coll, verts, faces=(), edges=()):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], list(edges), list(faces))
    me.update()
    return link(bpy.data.objects.new(name, me), coll)


def sphere(name, coll, center, radii, seg=32, rings=16, mat=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=rings, radius=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * radii[0], v.co.y * radii[1], v.co.z * radii[2])) + Vector(center)
    bm.to_mesh(me)
    bm.free()
    o = link(bpy.data.objects.new(name, me), coll)
    for p in me.polygons:
        p.use_smooth = True
    if mat:
        me.materials.append(mat)
    return o


def smooth(o):
    for p in o.data.polygons:
        p.use_smooth = True


def apply_modifiers(o):
    deps = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(deps)
    me = bpy.data.meshes.new_from_object(ev)
    old = o.data
    o.modifiers.clear()
    o.data = me
    bpy.data.meshes.remove(old)
    return o


def skin_mesh(name, coll, nodes: dict, edges: list, radii: dict, root: str, subsurf=2, mat=None):
    """Watertight tube mesh from a joint graph using the Skin modifier, then subdivided and applied."""
    names = list(nodes)
    idx = {n: i for i, n in enumerate(names)}
    me = bpy.data.meshes.new(name)
    me.from_pydata([nodes[n] for n in names], [(idx[a], idx[b]) for a, b in edges], [])
    me.update()
    o = link(bpy.data.objects.new(name, me), coll)
    o.modifiers.new("Skin", "SKIN")
    for n in names:
        r = radii[n]
        sv = me.skin_vertices[0].data[idx[n]]
        sv.radius = (r, r) if isinstance(r, (int, float)) else r
        sv.use_root = n == root
    if subsurf:
        s = o.modifiers.new("Sub", "SUBSURF")
        s.levels = s.render_levels = subsurf
    apply_modifiers(o)
    smooth(o)
    if mat:
        o.data.materials.append(mat)
    return o


# ----------------------------------------------------------------------------------------------- proportions
def skeleton(app: dict) -> dict:
    """Joint positions (A-pose) from the character's proportions. Everything scales with height."""
    H = app["height"]
    head_h = H * app["head_ratio"]
    neck_len = H * 0.035
    shoulder_z = H - head_h - neck_len
    leg = shoulder_z * app.get("leg_ratio", 0.56)
    sw = H * app.get("shoulder_width", 0.115)
    hw = H * app.get("hip_width", 0.075)
    up = H * 0.175 * app.get("arm_scale", 1.0)
    fo = H * 0.150 * app.get("arm_scale", 1.0)
    hand = H * 0.085 * app.get("arm_scale", 1.0)
    a = math.radians(app.get("arm_angle", 52))
    J = {
        "ground": (0, 0, 0),
        "pelvis": (0, 0, leg),
        "spine": (0, 0, leg + (shoulder_z - leg) * 0.35),
        "chest": (0, 0, leg + (shoulder_z - leg) * 0.72),
        "neck": (0, 0, shoulder_z),
        "head": (0, 0, shoulder_z + neck_len),
        "head_top": (0, 0, H),
    }
    for s, sx in (("L", 1), ("R", -1)):
        sh = Vector((sx * sw, 0, shoulder_z - H * 0.012))
        d = Vector((sx * math.cos(a), 0, -math.sin(a)))
        el = sh + d * up
        wr = el + d * fo
        J["clav." + s] = (sx * H * 0.02, 0, shoulder_z - H * 0.01)
        J["shoulder." + s] = tuple(sh)
        J["elbow." + s] = tuple(el + Vector((0, H * 0.008, 0)))
        J["wrist." + s] = tuple(wr)
        J["hand_end." + s] = tuple(wr + d * hand)
        J["hip." + s] = (sx * hw, 0, leg)
        J["knee." + s] = (sx * hw * 1.02, -H * 0.006, leg * 0.52)
        J["ankle." + s] = (sx * hw * 1.05, 0, leg * 0.075)
        J["toe." + s] = (sx * hw * 1.08, -H * 0.075, H * 0.012)
        J["toe_end." + s] = (sx * hw * 1.1, -H * 0.11, H * 0.012)
    return {k: Vector(v) for k, v in J.items()} | {"_H": H, "_head_h": head_h}


def arm_dir(J, s):
    return (J["wrist." + s] - J["elbow." + s]).normalized()


# ----------------------------------------------------------------------------------------------- body
def build_body(app, J, coll, skin_mat):
    H = J["_H"]
    t = app.get("thickness", 1.0)
    belly = app.get("belly", 0.0)
    nodes = {k: v for k, v in J.items() if not k.startswith("_") and k not in ("ground", "head_top", "toe_end.L", "toe_end.R", "hand_end.L", "hand_end.R")}
    nodes["head_in"] = J["head"] + Vector((0, 0, J["_head_h"] * 0.25))
    edges = [("pelvis", "spine"), ("spine", "chest"), ("chest", "neck"), ("neck", "head"), ("head", "head_in")]
    radii = {"pelvis": H * 0.085 * t, "spine": H * (0.075 + belly) * t, "chest": H * 0.088 * t, "neck": H * 0.032,
             "head": H * 0.034, "head_in": H * 0.03}
    for s, sx in (("L", 1), ("R", -1)):
        edges += [("chest", "clav." + s), ("clav." + s, "shoulder." + s), ("shoulder." + s, "elbow." + s), ("elbow." + s, "wrist." + s),
                  ("pelvis", "hip." + s), ("hip." + s, "knee." + s), ("knee." + s, "ankle." + s), ("ankle." + s, "toe." + s)]
        radii.update({"clav." + s: H * 0.05 * t, "shoulder." + s: H * 0.045 * t, "elbow." + s: H * 0.033 * t, "wrist." + s: H * 0.025,
                      "hip." + s: H * 0.058 * t, "knee." + s: H * 0.04 * t, "ankle." + s: H * 0.026, "toe." + s: H * 0.024})
        # hand: palm + four fingers (2 segments each) + thumb, laid out in the arm's frame
        d = arm_dir(J, s)
        side = Vector((0, -1, 0))                     # fingers spread front-to-back
        w = J["wrist." + s]
        hl = (J["hand_end." + s] - w).length
        palm = w + d * hl * 0.45
        nodes["palm." + s] = palm
        radii["palm." + s] = H * 0.03
        edges.append(("wrist." + s, "palm." + s))
        for i, off in enumerate((-1.5, -0.5, 0.5, 1.5)):
            base = palm + d * hl * 0.2 + side * off * H * 0.0105
            mid = base + d * hl * (0.28 - 0.03 * abs(off))
            tip = mid + d * hl * (0.22 - 0.03 * abs(off))
            for n, p in (("f%d_a" % i, base), ("f%d_b" % i, mid), ("f%d_c" % i, tip)):
                nodes[n + "." + s] = p
                radii[n + "." + s] = H * 0.0085
            edges += [("palm." + s, "f%d_a.%s" % (i, s)), ("f%d_a.%s" % (i, s), "f%d_b.%s" % (i, s)), ("f%d_b.%s" % (i, s), "f%d_c.%s" % (i, s))]
        tb = w + d * hl * 0.25 + side * H * 0.02
        tt = tb + (d * 0.55 + side * 0.85).normalized() * hl * 0.45
        nodes["th_a." + s], nodes["th_b." + s] = tb, tt
        radii["th_a." + s], radii["th_b." + s] = H * 0.011, H * 0.0095
        edges += [("palm." + s, "th_a." + s), ("th_a." + s, "th_b." + s)]
    body = skin_mesh("body", coll, nodes, edges, radii, "pelvis", subsurf=2, mat=skin_mat)
    return body, nodes


# ----------------------------------------------------------------------------------------------- head
def head_dims(app, J):
    hh = J["_head_h"]
    return {"cz": J["head"].z + hh * 0.5, "rx": hh * 0.5 * app.get("head_width", 0.92), "ry": hh * 0.5 * app.get("head_depth", 0.95),
            "rz": hh * 0.5, "jaw": app.get("jaw_taper", 0.22)}


def head_surface_y(hd, x, z):
    """Front (-y) surface of the head ellipsoid at (x, z), including the jaw taper."""
    u = (z - hd["cz"]) / hd["rz"]
    sx = 1.0 - hd["jaw"] * max(0.0, -u) ** 1.5
    q = 1.0 - (x / (hd["rx"] * sx)) ** 2 - u ** 2
    return -hd["ry"] * math.sqrt(max(q, 0.0))


def build_head(app, J, coll, skin_mat, mats):
    hd = head_dims(app, J)
    head = sphere("head", coll, (0, 0, hd["cz"]), (hd["rx"], hd["ry"], hd["rz"]), seg=64, rings=40, mat=skin_mat)
    for v in head.data.vertices:
        u = (v.co.z - hd["cz"]) / hd["rz"]
        if u < 0:
            k = 1.0 - hd["jaw"] * (-u) ** 1.5
            v.co.x *= k
            v.co.y *= 1.0 - hd["jaw"] * 0.3 * (-u) ** 1.5
        if v.co.y > 0:                                   # slightly flatter back of the head
            v.co.y *= 0.93
        cheek = math.exp(-((v.co.x / hd["rx"]) ** 2 - 0.42) ** 2 / 0.02 - (u + 0.28) ** 2 / 0.03)
        if v.co.y < 0:
            v.co.y -= cheek * hd["ry"] * 0.035 * app.get("cheeks", 1.0)
    head.data.update()
    parts = [head]
    nz = hd["cz"] - hd["rz"] * 0.12
    ny = head_surface_y(hd, 0, nz)
    ns = hd["rx"] * 0.16 * app.get("nose", 1.0)
    parts.append(sphere("nose", coll, (0, ny - ns * 0.35, nz), (ns * 0.8, ns * 0.75, ns * 0.75), seg=24, rings=12, mat=skin_mat))
    for sx in (1, -1):
        ez = hd["cz"] - hd["rz"] * 0.05
        parts.append(sphere("ear", coll, (sx * hd["rx"] * 0.97, hd["ry"] * 0.05, ez),
                            (hd["rx"] * 0.1, hd["rx"] * 0.17, hd["rz"] * 0.2 * app.get("ears", 1.0)), seg=20, rings=12, mat=skin_mat))
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = head
    bpy.ops.object.join()
    return head, hd


def build_eyes(app, J, hd, coll, mats):
    """Returns per side: (center, objects-on-eye-bone, lid object, brow object)."""
    out = {}
    er = hd["rx"] * 0.2 * app.get("eye_size", 1.0)
    spacing = hd["rx"] * 0.4 * app.get("eye_spacing", 1.0)
    ez = hd["cz"] + hd["rz"] * 0.02
    for s, sx in (("L", 1), ("R", -1)):
        x = sx * spacing
        y = head_surface_y(hd, x, ez) + er * 0.55
        c = Vector((x, y, ez))
        objs = [sphere("eye_white." + s, coll, c, (er, er, er), mat=mats["eye_white"]),
                sphere("iris." + s, coll, c + Vector((0, -er * 0.45, 0)), (er * 0.64, er * 0.64, er * 0.64), mat=mats["iris"]),
                sphere("pupil." + s, coll, c + Vector((0, -er * 0.6, 0)), (er * 0.36, er * 0.43, er * 0.36), mat=mats["pupil"]),
                sphere("glint." + s, coll, c + Vector((sx * -er * 0.22, -er * 0.92, er * 0.3)), (er * 0.12,) * 3, seg=12, rings=8,
                       mat=mats["glint"])]
        # upper lid: top half of a slightly larger sphere, rotated back so the eye is open at rest
        lid = sphere("lid." + s, coll, (0, 0, 0), (er * 1.2,) * 3, seg=32, rings=16, mat=mats["skin"])
        bm = bmesh.new()
        bm.from_mesh(lid.data)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -1e-6], context="VERTS")
        bm.to_mesh(lid.data)
        bm.free()
        rot = Matrix.Rotation(math.radians(-64), 4, "X")
        lid.data.transform(rot)
        lid.data.transform(Matrix.Translation(c))
        sol = lid.modifiers.new("thick", "SOLIDIFY")
        sol.thickness = er * 0.1
        sol.offset = -1.0
        apply_modifiers(lid)
        smooth(lid)
        lid.data.materials.append(mats["skin"])
        # brow: thick curved capsule above the eye
        bz = ez + er * 1.55
        by = head_surface_y(hd, x, bz) - er * 0.05
        brow = sphere("brow." + s, coll, (x, by, bz), (er * 1.15, er * 0.26, er * 0.3 * app.get("brow", 1.0)), seg=24, rings=10,
                      mat=mats["brow"])
        for v in brow.data.vertices:
            v.co.z -= ((v.co.x - x) / (er * 1.05)) ** 2 * er * 0.18
        out[s] = (c, objs, lid, brow, er)
    return out


MOUTH_SHAPES = {
    #           width  open  curve   round
    "Basis": (1.00, 0.16, 0.22, 0.0),
    "open": (0.95, 1.00, 0.00, 0.0),
    "smile": (1.18, 0.22, 0.95, 0.0),
    "frown": (0.9, 0.14, -0.85, 0.0),
    "wide": (1.30, 0.35, 0.10, 0.0),
    "round": (0.5, 0.75, 0.00, 1.0),
    "closed": (0.90, 0.0, 0.00, 0.0),
}


def build_mouth(app, J, hd, coll, mats):
    """A curved mouth patch that lies on the face; shape keys move points in (u, v) then re-project onto the head."""
    mz = hd["cz"] - hd["rz"] * 0.42
    mw = hd["rx"] * 0.33 * app.get("mouth", 1.0)
    mh = hd["rz"] * 0.16
    nu, nv = 28, 8

    def coords(width, opening, curve, rnd):
        pts = []
        for j in range(nv + 1):
            v = j / nv * 2 - 1                                        # -1 bottom lip .. 1 top lip
            for i in range(nu + 1):
                u = i / nu * 2 - 1
                half = max(0.0, 1 - u * u) ** (0.5 if rnd else 0.7)
                h = mh * (0.08 + opening) * half
                if rnd:                                                 # square-to-disc map: a round "O"
                    x = mw * width * u * math.sqrt(max(0.0, 1 - v * v / 2))
                    z = mz + mh * opening * 1.1 * v * math.sqrt(max(0.0, 1 - u * u / 2))
                else:
                    x = u * mw * width
                    z = mz + v * h + curve * mh * (u * u - 0.35)
                y = head_surface_y(hd, x, z) * 0.985 - mh * 0.16
                pts.append(Vector((x, y, z)))
        return pts

    faces = []
    for j in range(nv):
        for i in range(nu):
            a = j * (nu + 1) + i
            faces.append((a, a + 1, a + nu + 2, a + nu + 1))
    mouth = new_mesh_obj("mouth", coll, coords(*MOUTH_SHAPES["Basis"]), faces)
    mouth.data.materials.append(mats["mouth"])
    smooth(mouth)
    sol = mouth.modifiers.new("thick", "SOLIDIFY")
    sol.thickness = mh * 0.1
    sol.offset = 1.0
    apply_modifiers(mouth)
    mouth.shape_key_add(name="Basis", from_mix=False)
    for name, spec in MOUTH_SHAPES.items():
        if name == "Basis":
            continue
        kb = mouth.shape_key_add(name=name, from_mix=False)
        for i, p in enumerate(coords(*spec)):
            kb.data[i].co = p
    # lips: a soft rim around the mouth in the lip colour
    lips = sphere("lips", coll, (0, head_surface_y(hd, 0, mz) + mh * 0.06, mz), (mw * 1.08, mh * 0.18, mh * 0.42), seg=32, rings=12,
                  mat=mats["lips"])
    lips.hide_render = not app.get("lip_color")
    return mouth, lips, mz


def cut_cap(obj, plane_co, plane_no, keep_above=True):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    res = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=plane_co, plane_no=plane_no)
    del res
    no = Vector(plane_no)
    dead = [v for v in bm.verts if (v.co - Vector(plane_co)).dot(no) < -1e-6] if keep_above else \
        [v for v in bm.verts if (v.co - Vector(plane_co)).dot(no) > 1e-6]
    bmesh.ops.delete(bm, geom=dead, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()


def build_hair(app, J, hd, coll, mats):
    style = app.get("hair_style", "short")
    parts = []
    if style != "bald":
        cap = sphere("hair_cap", coll, (0, hd["ry"] * 0.04, hd["cz"] + hd["rz"] * 0.04),
                     (hd["rx"] * 1.08, hd["ry"] * 1.1, hd["rz"] * 1.08), seg=48, rings=28, mat=mats["hair"])
        front = hd["cz"] + hd["rz"] * app.get("hairline", 0.6)
        back = hd["cz"] - hd["rz"] * (0.55 if style in ("long", "ponytail", "bob") else 0.3)
        no = Vector((0, (front - back), 2 * hd["ry"])).normalized()
        cut_cap(cap, (0, 0, (front + back) / 2), tuple(no))
        if style == "balding":
            cut_cap(cap, (0, 0, hd["cz"] + hd["rz"] * 0.5), (0, 0, -1))
        sol = cap.modifiers.new("thick", "SOLIDIFY")
        sol.thickness = hd["rz"] * 0.05
        apply_modifiers(cap)
        smooth(cap)
        cap.data.materials.append(mats["hair"])
        parts.append(cap)
        if style in ("short", "fringe", "bob", "long", "ponytail", "bun") and not app.get("cap"):    # fringe sweep
            parts.append(sphere("fringe", coll, (hd["rx"] * 0.25, -hd["ry"] * 0.62, hd["cz"] + hd["rz"] * 0.74),
                                (hd["rx"] * 0.62, hd["ry"] * 0.32, hd["rz"] * 0.2), mat=mats["hair"]))
        if style == "bun":
            parts.append(sphere("bun", coll, (0, hd["ry"] * 0.55, hd["cz"] + hd["rz"] * 0.95), (hd["rx"] * 0.42,) * 3, mat=mats["hair"]))
        if style == "ponytail":
            parts.append(sphere("tail", coll, (0, hd["ry"] * 1.15, hd["cz"] - hd["rz"] * 0.15),
                                (hd["rx"] * 0.26, hd["ry"] * 0.3, hd["rz"] * 0.62), mat=mats["hair"]))
            parts.append(sphere("tie", coll, (0, hd["ry"] * 1.0, hd["cz"] + hd["rz"] * 0.3), (hd["rx"] * 0.14,) * 3, mat=mats["accent"]))
        if style in ("bob", "long"):
            for sx in (1, -1):
                parts.append(sphere("side", coll, (sx * hd["rx"] * 0.98, hd["ry"] * 0.25, hd["cz"] - hd["rz"] * (0.35 if style == "bob" else 0.7)),
                                    (hd["rx"] * 0.22, hd["ry"] * 0.75, hd["rz"] * (0.5 if style == "bob" else 0.95)), mat=mats["hair"]))
        if style == "curly":
            for i in range(14):
                a = i / 14 * 2 * math.pi
                parts.append(sphere("curl", coll, (math.cos(a) * hd["rx"] * 0.9, math.sin(a) * hd["ry"] * 0.9 + hd["ry"] * 0.1,
                                                   hd["cz"] + hd["rz"] * (0.55 + 0.12 * math.sin(3 * a))), (hd["rx"] * 0.32,) * 3, seg=16, rings=10,
                                    mat=mats["hair"]))
        if style == "spiky":
            for i in range(7):
                a = (i - 3) * 0.32
                bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=hd["rx"] * 0.22, depth=hd["rz"] * 0.55,
                                                location=(math.sin(a) * hd["rx"] * 0.6, hd["ry"] * 0.1, hd["cz"] + hd["rz"] * 1.05),
                                                rotation=(math.radians(-20), a, 0))
                cone = bpy.context.active_object
                bpy.context.collection.objects.unlink(cone) if cone.name in bpy.context.collection.objects else None
                coll.objects.link(cone) if cone.name not in coll.objects else None
                cone.data.materials.append(mats["hair"])
                parts.append(cone)
    else:
        pass
    if style == "balding":
        for sx in (1, -1):
            parts.append(sphere("side", coll, (sx * hd["rx"] * 0.9, hd["ry"] * 0.35, hd["cz"] - hd["rz"] * 0.05),
                                (hd["rx"] * 0.2, hd["ry"] * 0.55, hd["rz"] * 0.35), mat=mats["hair"]))
    if app.get("beard"):
        mz = hd["cz"] - hd["rz"] * 0.62
        parts.append(sphere("beard", coll, (0, head_surface_y(hd, 0, mz) + hd["ry"] * 0.18, mz),
                            (hd["rx"] * 0.62, hd["ry"] * 0.45, hd["rz"] * 0.42), mat=mats["hair"]))
    if app.get("mustache"):
        mz = hd["cz"] - hd["rz"] * 0.3
        parts.append(sphere("mustache", coll, (0, head_surface_y(hd, 0, mz) - hd["ry"] * 0.02, mz),
                            (hd["rx"] * 0.38, hd["ry"] * 0.1, hd["rz"] * 0.08), mat=mats["hair"]))
    return parts


def build_accessories(app, J, hd, coll, mats, eyes):
    parts = []
    if app.get("glasses"):
        for s, (c, _o, _l, _b, er) in eyes.items():
            bpy.ops.mesh.primitive_torus_add(major_radius=er * 1.45, minor_radius=er * 0.1, location=c + Vector((0, -er * 1.05, 0)),
                                             rotation=(math.radians(90), 0, 0), major_segments=32, minor_segments=8)
            t = bpy.context.active_object
            for cl in list(t.users_collection):
                cl.objects.unlink(t)
            coll.objects.link(t)
            t.data.materials.append(mats["frame"])
            parts.append(t)
        cl, cr = eyes["L"][0], eyes["R"][0]
        er = eyes["L"][4]
        parts.append(sphere("bridge", coll, ((cl.x + cr.x) / 2, cl.y - er * 1.1, cl.z + er * 0.2), ((cl.x - cr.x) / 2 - er * 1.4, er * 0.08, er * 0.08),
                            seg=12, rings=6, mat=mats["frame"]))
    if app.get("cap"):
        parts.append(sphere("cap", coll, (0, hd["ry"] * 0.02, hd["cz"] + hd["rz"] * 0.35), (hd["rx"] * 1.12, hd["ry"] * 1.12, hd["rz"] * 0.8),
                            mat=mats["accent"]))
        cut_cap(parts[-1], (0, 0, hd["cz"] + hd["rz"] * 0.38), (0, 0, 1))
        parts.append(sphere("brim", coll, (0, -hd["ry"] * 0.95, hd["cz"] + hd["rz"] * 0.4), (hd["rx"] * 0.75, hd["ry"] * 0.6, hd["rz"] * 0.04),
                            mat=mats["accent"]))
    return parts


# ----------------------------------------------------------------------------------------------- clothes
def build_clothes(app, J, nodes, coll, mats):
    H = J["_H"]
    t = app.get("thickness", 1.0)
    belly = app.get("belly", 0.0)
    out = []
    sleeve = app.get("sleeve", "long")       # long | short
    top = {"pelvis": J["pelvis"] + Vector((0, 0, H * 0.02)), "spine": J["spine"], "chest": J["chest"], "neck": J["neck"] + Vector((0, 0, H * 0.012))}
    tr = {"pelvis": H * 0.092 * t, "spine": H * (0.081 + belly) * t, "chest": H * 0.095 * t, "neck": H * 0.037}
    te = [("pelvis", "spine"), ("spine", "chest"), ("chest", "neck")]
    for s in ("L", "R"):
        top["clav." + s] = J["clav." + s]
        top["shoulder." + s] = J["shoulder." + s]
        tr["clav." + s], tr["shoulder." + s] = H * 0.058 * t, H * 0.052 * t
        te += [("chest", "clav." + s), ("clav." + s, "shoulder." + s)]
        if sleeve == "long":
            top["elbow." + s] = J["elbow." + s]
            top["cuff." + s] = J["wrist." + s] - arm_dir(J, s) * H * 0.012
            tr["elbow." + s], tr["cuff." + s] = H * 0.039 * t, H * 0.032
            te += [("shoulder." + s, "elbow." + s), ("elbow." + s, "cuff." + s)]
        else:
            top["sleeve." + s] = J["shoulder." + s] + (J["elbow." + s] - J["shoulder." + s]) * 0.55
            tr["sleeve." + s] = H * 0.05 * t
            te.append(("shoulder." + s, "sleeve." + s))
    shirt = skin_mesh("shirt", coll, top, te, tr, "pelvis", subsurf=2, mat=mats["shirt"])
    out.append(shirt)
    pn = {"waist": J["pelvis"] + Vector((0, 0, H * 0.035)), "pelvis": J["pelvis"]}
    pr = {"waist": H * 0.09 * t, "pelvis": H * 0.091 * t}
    pe = [("waist", "pelvis")]
    shorts = app.get("shorts", False)
    for s in ("L", "R"):
        pn["hip." + s] = J["hip." + s]
        pr["hip." + s] = H * 0.064 * t
        pe.append(("pelvis", "hip." + s))
        if shorts:
            pn["hem." + s] = J["hip." + s] + (J["knee." + s] - J["hip." + s]) * 0.7
            pr["hem." + s] = H * 0.05 * t
            pe.append(("hip." + s, "hem." + s))
        else:
            pn["knee." + s] = J["knee." + s]
            pn["hem." + s] = J["ankle." + s] + Vector((0, 0, H * 0.02))
            pr["knee." + s], pr["hem." + s] = H * 0.046 * t, H * 0.036
            pe += [("hip." + s, "knee." + s), ("knee." + s, "hem." + s)]
    pants = skin_mesh("pants", coll, pn, pe, pr, "waist", subsurf=2, mat=mats["pants"])
    out.append(pants)
    for s in ("L", "R"):
        a, tip = J["ankle." + s], J["toe_end." + s]
        c = (a + tip) / 2 + Vector((0, 0, H * 0.005))
        shoe = sphere("shoe." + s, coll, c, (H * 0.034, (a - tip).length * 0.62, H * 0.03), mat=mats["shoes"])
        out.append(shoe)
    if app.get("apron"):
        ap = sphere("apron", coll, (0, -H * 0.075 * t, J["pelvis"].z + H * 0.02), (H * 0.075, H * 0.03, H * 0.13), mat=mats["accent"])
        out.append(ap)
    if app.get("tie"):
        out.append(sphere("tie", coll, (0, -H * 0.09 * t, J["chest"].z - H * 0.02), (H * 0.014, H * 0.012, H * 0.075), mat=mats["accent"]))
    return out


# ----------------------------------------------------------------------------------------------- rig
DEFORM_SKIN = {"hips", "spine", "chest", "neck", "head"}


def build_rig(J, eyes, hd, mouth_z, coll):
    H = J["_H"]
    arm = bpy.data.armatures.new("rig")
    rig = link(bpy.data.objects.new("rig", arm), coll)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones

    def B(name, head, tail, parent=None, connect=False, deform=True, roll_to=FWD):
        b = eb.new(name)
        b.head, b.tail = Vector(head), Vector(tail)
        b.align_roll(roll_to)
        if parent:
            b.parent = eb[parent]
            b.use_connect = connect
        b.use_deform = deform
        return b

    B("root", (0, 0, 0), (0, H * 0.12, 0), deform=False, roll_to=Vector((0, 0, 1)))
    B("hips", J["pelvis"], J["spine"], "root")
    B("spine", J["spine"], J["chest"], "hips", True)
    B("chest", J["chest"], J["neck"], "spine", True)
    B("neck", J["neck"], J["head"], "chest", True)
    B("head", J["head"], J["head_top"], "neck", True)
    for s in ("L", "R"):
        c, _o, _l, _b, er = eyes[s]
        B("eye." + s, c, c + Vector((0, -er * 1.4, 0)), "head", deform=False, roll_to=Vector((0, 0, 1)))
        B("lid." + s, c, c + Vector((0, -er * 1.4, 0)), "head", deform=False, roll_to=Vector((0, 0, 1)))
        bc = eyes[s][3].location + Vector(eyes[s][3].data.vertices[0].co) * 0      # brow object origin is world origin
        bz = c.z + er * 1.55
        B("brow." + s, (c.x, c.y, bz), (c.x, c.y - er, bz), "head", deform=False, roll_to=Vector((0, 0, 1)))
        del bc
        B("clav." + s, J["clav." + s], J["shoulder." + s], "chest")
        B("upper_arm." + s, J["shoulder." + s], J["elbow." + s], "clav." + s, True)
        B("forearm." + s, J["elbow." + s], J["wrist." + s], "upper_arm." + s, True)
        B("hand." + s, J["wrist." + s], J["wrist." + s] + arm_dir(J, s) * (J["hand_end." + s] - J["wrist." + s]).length * 0.42,
          "forearm." + s, True)
        d = arm_dir(J, s)
        hl = (J["hand_end." + s] - J["wrist." + s]).length
        palm = J["wrist." + s] + d * hl * 0.62
        B("fingers1." + s, palm, palm + d * hl * 0.22, "hand." + s)
        B("fingers2." + s, palm + d * hl * 0.22, palm + d * hl * 0.48, "fingers1." + s, True)
        tb = J["wrist." + s] + d * hl * 0.25 + Vector((0, -H * 0.02, 0))
        tt = tb + (d * 0.55 + Vector((0, -0.85, 0))).normalized() * hl * 0.45
        B("thumb." + s, tb, tt, "hand." + s)
        B("thigh." + s, J["hip." + s], J["knee." + s], "hips")
        B("shin." + s, J["knee." + s], J["ankle." + s], "thigh." + s, True)
        B("foot." + s, J["ankle." + s], J["toe." + s], "shin." + s, True, roll_to=Vector((0, 0, 1)))
        B("toe." + s, J["toe." + s], J["toe_end." + s], "foot." + s, True, roll_to=Vector((0, 0, 1)))
        # IK controls (not deforming)
        a = J["ankle." + s]
        B("foot_ik." + s, (a.x, a.y, 0.0), (a.x, a.y - H * 0.1, 0.0), "root", deform=False, roll_to=Vector((0, 0, 1)))
        k = J["knee." + s]
        B("knee_pole." + s, (k.x, k.y - H * 0.35, k.z), (k.x, k.y - H * 0.4, k.z), "root", deform=False)
        w = J["wrist." + s]
        B("hand_ik." + s, w, w + d * H * 0.05, "root", deform=False)
    # face control bone: custom properties drive the mouth shape keys
    B("face", (0, -hd["ry"] * 1.6, mouth_z), (0, -hd["ry"] * 1.6, mouth_z + H * 0.03), "head", deform=False, roll_to=FWD)
    bpy.ops.object.mode_set(mode="POSE")
    for s in ("L", "R"):
        shin = rig.pose.bones["shin." + s]
        ik = shin.constraints.new("IK")
        ik.target, ik.subtarget = rig, "foot_ik." + s
        ik.pole_target, ik.pole_subtarget = rig, "knee_pole." + s
        ik.pole_angle = math.radians(-90)
        ik.chain_count = 2
        foot = rig.pose.bones["foot." + s]
        cr = foot.constraints.new("COPY_ROTATION")
        cr.target, cr.subtarget = rig, "foot_ik." + s
        cr.influence = 0.0
        fa = rig.pose.bones["forearm." + s]
        aik = fa.constraints.new("IK")
        aik.target, aik.subtarget = rig, "hand_ik." + s
        aik.chain_count = 2
        aik.influence = 0.0                                   # FK by default; IK switch for contact poses
    for pb in rig.pose.bones:
        pb.rotation_mode = "XYZ"
    face = rig.pose.bones["face"]
    for k in MOUTH_SHAPES:
        if k != "Basis":
            face[k] = 0.0
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def bind_rigid(obj, rig, bone):
    mw = obj.matrix_world.copy()
    obj.parent = rig
    obj.parent_type = "BONE"
    obj.parent_bone = bone
    obj.matrix_world = mw


def drive_mouth(mouth, rig):
    for kb in mouth.data.shape_keys.key_blocks[1:]:
        fc = kb.driver_add("value")
        drv = fc.driver
        drv.type = "AVERAGE"
        var = drv.variables.new()
        var.type = "SINGLE_PROP"
        var.targets[0].id = rig
        var.targets[0].data_path = 'pose.bones["face"]["%s"]' % kb.name


# ----------------------------------------------------------------------------------------------- weights
def dist_seg(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return (p - (a + ab * t)).length


def measure_weights(obj, rig):
    deform = {b.name for b in rig.data.bones if b.use_deform}
    gi = {g.index: g.name for g in obj.vertex_groups}
    unweighted = leak = side = 0
    for v in obj.data.vertices:
        tot = sum(g.weight for g in v.groups if gi.get(g.group) in deform)
        if tot < 1e-4:
            unweighted += 1
        if abs(v.co.x) > 0.04:
            side += 1
            other = ".R" if v.co.x > 0 else ".L"
            if any(gi.get(g.group, "").endswith(other) and g.weight > 0.15 for g in v.groups):
                leak += 1
    n = max(1, len(obj.data.vertices))
    return round(100.0 * unweighted / n, 3), round(100.0 * leak / max(1, side), 3)


def fallback_weights(obj, rig):
    """Deterministic: two nearest deform bones on the vertex's own side, inverse-distance^4, normalised."""
    for g in list(obj.vertex_groups):
        obj.vertex_groups.remove(g)
    bones = [(b.name, b.head_local.copy(), b.tail_local.copy()) for b in rig.data.bones if b.use_deform]
    groups = {n: obj.vertex_groups.new(name=n) for n, _a, _b in bones}
    for v in obj.data.vertices:
        cand = [(dist_seg(v.co, a, b), n) for n, a, b in bones
                if not ((v.co.x > 0.02 and n.endswith(".R")) or (v.co.x < -0.02 and n.endswith(".L")))]
        cand.sort()
        ws = [(n, 1.0 / (d + 1e-3) ** 4) for d, n in cand[:2]]
        tot = sum(w for _n, w in ws)
        for n, w in ws:
            groups[n].add([v.index], w / tot, "REPLACE")


def mask_covered_skin(body, rig, app, J):
    """Delete body skin that clothes and shoes cover, so it can never poke through them."""
    H = J["_H"]
    gi = {g.index: g.name for g in body.vertex_groups}
    long_sleeve = app.get("sleeve", "long") == "long"
    long_pants = not app.get("shorts", False)
    neck_z = J["neck"].z - H * 0.008
    dead = set()
    for v in body.data.vertices:
        if not v.groups:
            continue
        g = gi[max(v.groups, key=lambda e: e.weight).group]
        base = g.split(".")[0]
        side = g[-1]
        co = v.co
        if base in ("hips", "spine", "chest", "clav") and co.z < neck_z:
            dead.add(v.index)
        elif base == "upper_arm":
            sh, el = J["shoulder." + side], J["elbow." + side]
            if long_sleeve or (co - sh).length < (el - sh).length * 0.5:
                dead.add(v.index)
        elif base == "forearm" and long_sleeve and (co - J["wrist." + side]).length > H * 0.03:
            dead.add(v.index)
        elif base == "thigh":
            hip, kn = J["hip." + side], J["knee." + side]
            if long_pants or co.z > hip.z - (hip.z - kn.z) * 0.65:
                dead.add(v.index)
        elif base == "shin" and long_pants and co.z > J["ankle." + side].z + H * 0.03:
            dead.add(v.index)
        elif base in ("foot", "toe"):
            dead.add(v.index)
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in dead], context="VERTS")
    bm.to_mesh(body.data)
    bm.free()
    return len(dead)


def skin_to_rig(obj, rig):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    method = "bone_heat"
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except Exception as e:                    # noqa: BLE001 - recorded in the build report
        method = "bone_heat_error:" + type(e).__name__
    u, l = measure_weights(obj, rig)
    if method != "bone_heat" or u > 0.5 or l > 1.0:
        method = f"fallback(after {method}: unweighted={u}%, leak={l}%)"
        fallback_weights(obj, rig)
        if obj.parent != rig:
            obj.parent = rig
        if not any(m.type == "ARMATURE" for m in obj.modifiers):
            m = obj.modifiers.new("Armature", "ARMATURE")
            m.object = rig
    u, l = measure_weights(obj, rig)
    return {"object": obj.name, "method": method, "unweighted_pct": u, "leak_pct": l, "vertices": len(obj.data.vertices)}


# ----------------------------------------------------------------------------------------------- top level
def build_character(char: dict, coll=None) -> dict:
    """Build one character into its own collection; returns {'rig', 'objects', 'report'}."""
    app = char["appearance"]
    cid = char["id"]
    coll = coll or bpy.data.collections.new(cid)
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    p = app["palette"]
    mats = {
        "skin": material(cid + "_skin", p["skin"], 0.5, sss=0.15, spec=0.35),
        "eye_white": material(cid + "_eyewhite", "#F7F5F0", 0.25),
        "iris": material(cid + "_iris", p["iris"], 0.3, coat=0.5),
        "pupil": material(cid + "_pupil", "#14110F", 0.2),
        "glint": material(cid + "_glint", "#FFFFFF", 0.1, emit=3.0),
        "brow": material(cid + "_brow", p.get("brow", p["hair"]), 0.7),
        "hair": material(cid + "_hair", p["hair"], 0.55, spec=0.5),
        "mouth": material(cid + "_mouth", "#5A1E22", 0.6),
        "lips": material(cid + "_lips", p.get("lips", p["skin"]), 0.45),
        "shirt": material(cid + "_shirt", p["shirt"], 0.75),
        "pants": material(cid + "_pants", p["pants"], 0.8),
        "shoes": material(cid + "_shoes", p["shoes"], 0.45),
        "accent": material(cid + "_accent", p.get("accent", p["shirt"]), 0.6),
        "frame": material(cid + "_frame", p.get("frame", "#2B2B2B"), 0.3),
    }
    J = skeleton(app)
    body, nodes = build_body(app, J, coll, mats["skin"])
    head, hd = build_head(app, J, coll, mats["skin"], mats)
    eyes = build_eyes(app, J, hd, coll, mats)
    mouth, lips, mz = build_mouth(app, J, hd, coll, mats)
    hair = build_hair(app, J, hd, coll, mats)
    acc = build_accessories(app, J, hd, coll, mats, eyes)
    clothes = build_clothes(app, J, nodes, coll, mats)
    rig = build_rig(J, eyes, hd, mz, coll)
    rig.name = cid + "_rig"
    rig.data.name = cid + "_rig"
    reports = [skin_to_rig(o, rig) for o in [body] + [c for c in clothes if not c.name.startswith(("shoe", "apron", "tie"))]]
    masked = mask_covered_skin(body, rig, app, J)
    reports[0]["masked_under_clothes"] = masked
    reports[0]["unweighted_pct"], reports[0]["leak_pct"] = measure_weights(body, rig)
    for c in clothes:
        if c.name.startswith("shoe"):
            bind_rigid(c, rig, "foot." + c.name.split(".")[-1][0])
        elif c.name.startswith(("apron", "tie")):
            bind_rigid(c, rig, "hips" if c.name.startswith("apron") else "chest")
    for o in [head, mouth, lips] + hair + acc:
        bind_rigid(o, rig, "head")
    for s, (c, objs, lid, brow, _er) in eyes.items():
        for o in objs:
            bind_rigid(o, rig, "eye." + s)
        bind_rigid(lid, rig, "lid." + s)
        bind_rigid(brow, rig, "brow." + s)
    drive_mouth(mouth, rig)
    for o in coll.objects:
        o.name = f"{cid}:{o.name}"
    rig.name = cid + "_rig"
    meshes = [o for o in coll.objects if o.type == "MESH"]
    report = {
        "id": cid,
        "height_m": J["_H"],
        "objects": len(meshes),
        "vertices": sum(len(o.data.vertices) for o in meshes),
        "polygons": sum(len(o.data.polygons) for o in meshes),
        "materials": sorted({m.name for o in meshes for m in o.data.materials if m}),
        "bones": len(rig.data.bones),
        "deform_bones": len([b for b in rig.data.bones if b.use_deform]),
        "ik": ["shin.L", "shin.R", "forearm.L (off)", "forearm.R (off)"],
        "mouth_shape_keys": [k.name for k in mouth.data.shape_keys.key_blocks],
        "face_controls": [k for k in MOUTH_SHAPES if k != "Basis"],
        "skinning": reports,
    }
    return {"rig": rig, "collection": coll, "report": report, "mouth": mouth, "joints": J, "head": hd}
