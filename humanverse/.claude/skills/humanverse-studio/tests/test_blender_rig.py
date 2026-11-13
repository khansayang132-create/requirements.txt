"""Builds a real character in Blender (needs bpy or Blender's Python); about 20 s."""
import math

import pytest

bpy = pytest.importorskip("bpy")

CHAR = {"id": "CHAR-TEST-001", "appearance": {"height": 1.3, "head_ratio": 0.22, "leg_ratio": 0.5, "hair_style": "bob", "glasses": True,
        "palette": {"skin": "#A86B47", "hair": "#2A1B14", "iris": "#5B3A1E", "shirt": "#F2B134", "pants": "#3E6FB0", "shoes": "#E4573D"}}}


@pytest.fixture(scope="module")
def built():
    import hvchar
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return hvchar.build_character(CHAR)


def test_rig_and_weights(built):
    r = built["report"]
    assert r["bones"] == 41 and r["deform_bones"] >= 25
    for s in r["skinning"]:
        assert s["unweighted_pct"] < 0.5 and s["leak_pct"] < 1.0, s
    assert r["mouth_shape_keys"][0] == "Basis" and len(r["mouth_shape_keys"]) == 7


def test_axis_conventions(built):
    rig = built["rig"]
    pb = rig.pose.bones
    for b in pb:
        b.rotation_mode = "XYZ"

    def hand():
        bpy.context.view_layer.update()
        return rig.matrix_world @ pb["hand.L"].head

    rest = hand()
    pb["upper_arm.L"].rotation_euler = (math.radians(60), 0, 0)
    assert hand().y < rest.y - 0.1                       # +X swings forward (-Y)
    pb["upper_arm.L"].rotation_euler = (0, 0, math.radians(30))
    assert hand().z > rest.z + 0.05                      # +Z raises the left arm
    pb["upper_arm.L"].rotation_euler = (0, 0, 0)


def test_face_controls_drive_shape_keys(built):
    rig, mouth = built["rig"], built["mouth"]
    rig.pose.bones["face"]["smile"] = 1.0
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(1)
    assert mouth.data.shape_keys.key_blocks["smile"].value == pytest.approx(1.0)


def test_walk_keeps_planted_feet(built):
    import hvanim
    p = hvanim.Performer(built["rig"], 24, seed="t")
    p.place(1, -1.5, 0, 90)
    p.stand(1)
    p.walk(5, [(-1.5, 0.0), (0.5, 0.0)])
    slide = hvanim.foot_slide_report(built["rig"], p.stance_frames)
    assert max(slide.values()) < 2.0, slide


def test_held_prop_follows_the_palm(built):
    """A prop attached to a hand is keyed to that palm (+ offset) on every frame, even while the arm moves.
    Found in the pilot: the kite was keyed to fixed points and hung in front of Noor instead of in her hand."""
    import build_scene
    rig = built["rig"]
    pb = rig.pose.bones["upper_arm.R"]
    pb.rotation_mode = "XYZ"
    for f, ang in ((1, 0), (12, 70)):
        pb.rotation_euler = (math.radians(ang), 0, 0)
        pb.keyframe_insert("rotation_euler", frame=f)
    sc = bpy.context.scene
    prop = bpy.data.objects.new("held", None)
    sc.collection.objects.link(prop)
    off = (0.0, -0.05, 0.2)
    build_scene.bake_attach(sc, prop, [{"f0": 1, "f1": 12, "char": "c", "hand": "R", "offset": off}], {"c": rig})
    seen = []
    for f in (1, 6, 12):
        sc.frame_set(f)
        palm = build_scene.palm_world(rig, "R")
        seen.append(palm.copy())
        assert (prop.matrix_world.translation - palm).length == pytest.approx(math.dist((0, 0, 0), off), abs=1e-4)
    assert (seen[0] - seen[2]).length > 0.1                   # the hand really moved, and the prop went with it
