"""Tests for the real-3D character backend (render3d/ + wonderland/render/three_backend.py).

The rendering tests skip cleanly when node / playwright / chromium / three are not installed;
the fallback tests always run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wonderland import config  # noqa: E402
from wonderland.departments import animation  # noqa: E402
from wonderland.render import three_backend as tb  # noqa: E402
from wonderland.render.canvas import hex_rgb  # noqa: E402
from wonderland.render.characters import Pose, bounding_height, hand_pos, head_top  # noqa: E402
from wonderland.render.stage import Actor, Renderer, Shot  # noqa: E402

UNI = config.load_universe()
OK, WHY = tb.available()
needs_3d = pytest.mark.skipif(not OK, reason=f"3D backend unavailable: {WHY}")


@pytest.fixture(scope="module")
def session():
    s = tb.Session(UNI["characters"], 1080, 1920)
    yield s
    s.close()


def _solo(session, cid, pose, side=1.0, yaw=0.0, shadow=False):
    return session.render([tb.pose_record(cid, pose, side, yaw)], shadow=shadow)


def _unpremultiplied_opaque(layer):
    a = layer.rgba[..., 3]
    return layer.rgba[a == 255][:, :3]


@needs_3d
@pytest.mark.parametrize("spec", UNI["characters"], ids=lambda s: s["id"])
def test_frame_has_real_alpha_and_bible_colour(session, spec):
    layer = _solo(session, spec["id"], Pose(x=540, y=1340, scale=0.9))
    a = layer.rgba[..., 3]
    assert (a == 0).mean() > 0.2, "the background must be transparent"
    assert (a == 255).sum() > 20000, "the character must be opaque"
    assert ((a > 0) & (a < 255)).sum() > 200, "edges must be antialiased (partial alpha)"
    px = _unpremultiplied_opaque(layer).astype(int)
    q = (px // 16) * 16 + 8                                   # dominant colour = most common 16-level bin
    keys, counts = np.unique(q[:, 0] * 65536 + q[:, 1] * 256 + q[:, 2], return_counts=True)
    k = keys[counts.argmax()]
    dom = np.array([k // 65536, (k // 256) % 256, k % 256])
    body = np.array(hex_rgb(spec["colors"]["body"]))
    assert np.abs(dom - body).max() <= 24, f"dominant {dom.tolist()} vs bible body {body.tolist()}"


@needs_3d
@pytest.mark.parametrize("spec", UNI["characters"], ids=lambda s: s["id"])
@pytest.mark.parametrize("scale,yaw", [(1.0, 0.0), (0.74, 26.0)])
def test_feet_height_and_anchors_match_2d_rig(session, spec, scale, yaw):
    p = Pose(x=540, y=1340, scale=scale)
    layer = _solo(session, spec["id"], p, 1.0, yaw)
    rows = np.where(layer.rgba[..., 3].max(axis=1) > 128)[0]
    top, bottom = layer.box[1] + rows[0], layer.box[1] + rows[-1] + 1
    assert abs(bottom - p.y) <= 6, f"feet at {bottom}, ground line {p.y}"
    want = bounding_height(spec) * scale
    assert abs((bottom - top) - want) <= 0.05 * want, f"height {bottom - top} vs {want:.0f}"
    an = layer.anchors[spec["id"]]
    assert np.hypot(*np.subtract(an["head_top"], head_top(p))) <= 10
    assert np.hypot(*np.subtract(an["hand_r"], hand_pos(p, 1))) <= 25
    assert np.hypot(*np.subtract(an["hand_l"], hand_pos(p, -1))) <= 25
    assert an["feet"] == (p.x, p.y)


@needs_3d
def test_raised_arm_anchor_follows_pose(session):
    p = Pose(x=540, y=1340, scale=0.9, arm_r=150)
    an = _solo(session, "bobo", p).anchors["bobo"]
    assert an["hand_r"][1] < 1340 - 0.9 * 230, "a raised arm puts the hand above the shoulder"
    assert np.hypot(*np.subtract(an["hand_r"], hand_pos(p, 1))) <= 40


@needs_3d
def test_same_input_gives_identical_pixels(session):
    recs = [tb.pose_record("mimi", Pose(x=315, y=1340, scale=0.86, arm_r=120, mouth=0.6, mood="wow"), 1.0, 26.0),
            tb.pose_record("toto", Pose(x=765, y=1340, scale=0.86, head_tilt=6, step=1.3, flip=True), -1.0, -26.0)]
    a, b = session.render(recs), session.render(recs)
    assert a.box == b.box and np.array_equal(a.rgba, b.rgba)
    with tb.Session(UNI["characters"], 1080, 1920) as other:      # a fresh browser too
        c = other.render(recs)
    assert c.box == a.box and np.array_equal(c.rgba, a.rgba)


@needs_3d
def test_stage_frame_with_3d_layer_is_deterministic(session):
    shot = Shot(env="night", actors=[Actor("bobo", 315, action="sleep"), Actor("lolo", 765, action="wave", facing=-1,
                                                                                    hold={"name": "balloon", "color": "red", "side": 1})],
                caption="Good night, moon.", fx="zzz", duration=2.0)
    r = Renderer(UNI)
    r.three = session
    f1, f2 = r.frame(shot, 0.5, 3.5), r.frame(shot, 0.5, 3.5)
    assert f1.size == (1080, 1920) and np.array_equal(np.asarray(f1), np.asarray(f2))
    assert set(r._anchors) == {"bobo", "lolo"}


@needs_3d
def test_dead_browser_raises_instead_of_hanging():
    s = tb.Session(UNI["characters"][:1], 270, 480, frame_timeout=20)
    s.proc.kill()
    s.proc.wait()
    with pytest.raises(tb.ThreeError):
        s.render([{"id": UNI["characters"][0]["id"], "x": 540, "y": 1340, "scale": 0.9, "side": 1, "yaw": 0}])


def _no_node(monkeypatch):
    monkeypatch.setattr(tb.shutil, "which", lambda name: None)
    tb.available.cache_clear()


def test_auto_falls_back_to_flat_without_node(monkeypatch):
    _no_node(monkeypatch)
    try:
        used, why = animation.resolve_backend("auto")
        assert used == "flat" and "node" in why
        assert animation.resolve_backend("flat") == ("flat", "requested flat")
    finally:
        tb.available.cache_clear()


def test_three_raises_clear_error_without_node(monkeypatch, tmp_path):
    _no_node(monkeypatch)
    try:
        with pytest.raises(animation.RenderError, match="3D backend requested but unavailable: node not found"):
            animation.resolve_backend("three")
        shot = Shot(env="meadow", actors=[Actor("bobo", 540)], duration=0.25)
        with pytest.raises(animation.RenderError, match="node not found"):
            animation.render_video([shot], UNI, tmp_path / "x.mp4", tmp_path / "w", width=270, height=480, workers=1, backend="three")
    finally:
        tb.available.cache_clear()


def test_flat_render_video_reports_backend(tmp_path):
    shot = Shot(env="meadow", actors=[Actor("bobo", 540)], duration=0.25)
    rep = animation.render_video([shot], UNI, tmp_path / "x.mp4", tmp_path / "w", width=270, height=480, workers=1, backend="flat")
    assert rep["backend"] == "flat" and rep["backend_reason"] == "requested flat" and rep["frames"] == 6
