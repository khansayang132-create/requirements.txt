"""Multi-style design engine: originality, identity across styles, QC that rejects broken designs, a real render."""
import json
import shutil

import numpy as np
import pytest
from PIL import Image

from cartoon_studio import engine
from cartoon_studio.design import engine as E
from cartoon_studio.design import qc
from cartoon_studio.design.build import EXISTING_NAMES
from cartoon_studio.design.styles import STYLES

renderer_ready = pytest.mark.skipif(not (engine.available()[0] and shutil.which("node")), reason="3D renderer not available")


def test_fifteen_distinct_styles():
    assert len(STYLES) == 15
    looks = {(s.mode, s.outline > 0, round(s.head, 2), s.body, round(s.eye, 2), s.grade) for s in STYLES.values()}
    assert len(looks) == 15                                   # no two styles share their whole rendering recipe
    assert {s.mode for s in STYLES.values()} == set(range(7))  # all seven shading models are used


def test_five_original_characters_per_style_with_unique_safe_names():
    taken = set(EXISTING_NAMES)
    chars = [c for sid in STYLES for c in E.generate(sid, 5, 1, taken)]
    assert len(chars) == 75
    names = [c.name for c in chars]
    assert len(set(names)) == 75 and not set(names) & EXISTING_NAMES
    assert not any(b in n.lower() for n in names for b in E.BLOCKED_NAME_PARTS)
    for sid in STYLES:                                        # within a style every character is its own design
        cast = [c for c in chars if c.style == sid]
        assert len({(c.species, c.colors["body"], c.clothing["accessory"]) for c in cast}) == 5


def test_comparison_changes_only_the_rendering_never_the_identity():
    c = E.generate("01-cinematic-3d", 1)[0]
    specs = [c.spec(STYLES[s]) for s in ("01-cinematic-3d", "06-anime", "08-clay", "09-storybook", "13-scifi")]
    for s in specs:
        assert (s["species"], s["colors"], s["clothing"], s["name"]) == (c.species, c.colors, c.clothing, c.name)
    assert len({json.dumps(s["style"], sort_keys=True) for s in specs}) == 5


def test_interface_rejects_unknown_options():
    with pytest.raises(ValueError):
        E.custom({"species": "dragon"})
    with pytest.raises(ValueError):
        E.custom({"body": "red; rm -rf /"})
    c, pose = E.custom({"style": "06-anime", "species": "cat", "age": "teen", "build": "tall", "accessory": "bow",
                        "expression": "wow", "animation": "wave", "camera": "side", "body": "#112233"})
    assert c.colors["body"] == "#112233" and pose["yaw"] == 90.0 and pose["mood"] == "wow" and pose["arm_r"] == 140


def _fake_character(tmp_path, front: np.ndarray, sid="01-cinematic-3d"):
    d = tmp_path / "x"
    (d / "views").mkdir(parents=True)
    for v in ("front", "three-quarter", "side", "back"):
        Image.fromarray(front, "RGBA").save(d / "views" / f"{v}.png")
    for f in ("turnaround", "expression_sheet", "proportions", "palette", "pose_sheet"):
        Image.new("RGB", (600, 400), "white").save(d / f"{f}.png")
    Image.new("RGB", (3000, 2200), "white").save(d / "character_sheet.png")
    (d / "character.json").write_text(json.dumps({"id": "x", "name": "X", "style": sid, "measured": {"head_ratio": 0.5},
                                                  "colors": {"body": "#E8A86B", "accent": "#3D7DD8"}}))
    return d


def test_qc_rejects_blank_and_cut_off_designs(tmp_path):
    blank = np.zeros((900, 600, 4), np.uint8)                 # transparent nothing
    rep = qc.check_character(_fake_character(tmp_path, blank))
    assert rep["status"] == "FAIL" and rep["checks"]["visual_quality"]["status"] == "FAIL"
    block = np.full((900, 600, 4), 255, np.uint8)             # a solid block touching every edge, wrong colours
    rep = qc.check_character(_fake_character(tmp_path / "b", block))
    assert rep["status"] == "FAIL" and rep["checks"]["color_consistency"]["status"] == "FAIL"


@renderer_ready
def test_real_render_produces_verified_references(tmp_path):
    c = E.generate("08-clay", 1)[0]
    r = E.Renderer([c])
    try:
        res = E.render_character(c, tmp_path, r)
    finally:
        r.close()
    rep = qc.check_character(tmp_path / c.id)
    assert rep["status"] == "PASS", {k: v for k, v in rep["checks"].items() if v["status"] != "PASS"}
    front = Image.open(tmp_path / c.id / "views" / "front.png")
    assert front.mode == "RGBA" and front.height > 600
    a = np.asarray(front)[..., 3]
    assert a[0, 0] == 0 and a.max() == 255                    # real transparency around a real figure
    assert len(res["files"]) == 11
