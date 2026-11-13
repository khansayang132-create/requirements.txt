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
