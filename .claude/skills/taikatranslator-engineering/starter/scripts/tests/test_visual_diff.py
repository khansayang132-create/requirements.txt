"""Unit tests for visual_diff.py. The comparison logic runs on synthetic images;
the render test runs only where LibreOffice and pdftoppm are installed."""
import importlib.util
import json
import os
import shutil
import sys

import pytest
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("visual_diff", os.path.join(HERE, "..", "visual_diff.py"))
vd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vd)


def page(path, text_box=(20, 20, 80, 30), size=(100, 140), clip=False):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    if text_box:
        d.rectangle(text_box, fill="black")
    if clip:
        d.rectangle((size[0] - 2, 50, size[0] - 1, 60), fill="black")
    img.save(path)
    return str(path)


def baseline(tmp_path, *pages):
    bdir = tmp_path / "baseline"
    bdir.mkdir()
    for i, p in enumerate(pages, start=1):
        shutil.copy(p, bdir / f"page-{i}.png")
    return str(bdir), {"dpi": 72, "tools": vd.tool_versions()}


def test_identical_pages_pass(tmp_path):
    a = page(tmp_path / "a.png")
    bdir, man = baseline(tmp_path, a)
    r = vd.compare_dirs([a], bdir, str(tmp_path / "out"), 0.002, 32, 4, man)
    assert r["passed"], r
    assert r["pages"][0]["changedFraction"] == 0
    assert json.load(open(tmp_path / "out" / "report.json"))["passed"]


def test_moved_text_fails_and_writes_diff_image(tmp_path):
    base = page(tmp_path / "base.png", text_box=(20, 20, 80, 30))
    moved = page(tmp_path / "moved.png", text_box=(20, 40, 80, 50))
    bdir, man = baseline(tmp_path, base)
    r = vd.compare_dirs([moved], bdir, str(tmp_path / "out"), 0.002, 32, 4, man)
    assert not r["passed"]
    assert "pixels changed" in r["problems"][0]
    assert (tmp_path / "out" / "diff-1.png").exists()


def test_threshold_is_configurable(tmp_path):
    base = page(tmp_path / "base.png", text_box=(20, 20, 80, 30))
    nudged = page(tmp_path / "nudged.png", text_box=(20, 20, 81, 30))  # 11 px of 14,000
    bdir, man = baseline(tmp_path, base)
    assert not vd.compare_dirs([nudged], bdir, str(tmp_path / "o1"), 0.0001, 32, 4, man)["passed"]
    assert vd.compare_dirs([nudged], bdir, str(tmp_path / "o2"), 0.01, 32, 4, man)["passed"]


def test_blank_page_and_page_count(tmp_path):
    base = page(tmp_path / "base.png")
    blank = page(tmp_path / "blank.png", text_box=None)
    bdir, man = baseline(tmp_path, base)
    r = vd.compare_dirs([base, blank], bdir, str(tmp_path / "out"), 0.002, 32, 4, man)
    assert not r["passed"]
    assert any("page count 2, baseline 1" in p for p in r["problems"])
    assert any("page 2 is blank" in p for p in r["problems"])


def test_clipping_at_page_edge(tmp_path):
    clipped = page(tmp_path / "clip.png", clip=True)
    bdir, man = baseline(tmp_path, clipped)
    r = vd.compare_dirs([clipped], bdir, str(tmp_path / "out"), 0.002, 32, 4, man)
    assert not r["passed"]
    assert "possible clipping" in r["problems"][0]


def test_size_mismatch(tmp_path):
    a = page(tmp_path / "a.png", size=(100, 140))
    b = page(tmp_path / "b.png", size=(140, 100))
    bdir, man = baseline(tmp_path, b)
    r = vd.compare_dirs([a], bdir, str(tmp_path / "out"), 0.002, 32, 4, man)
    assert not r["passed"] and "size" in r["problems"][0]


def test_tool_version_drift_is_a_warning(tmp_path):
    a = page(tmp_path / "a.png")
    bdir, _ = baseline(tmp_path, a)
    r = vd.compare_dirs([a], bdir, str(tmp_path / "out"), 0.002, 32, 4, {"dpi": 72, "tools": {"soffice": "LibreOffice 1.0"}})
    assert r["passed"]
    assert any("soffice differs" in w for w in r["warnings"])


def test_missing_input_is_usage_error(tmp_path):
    assert vd.main(["compare", str(tmp_path / "none.docx"), "--baseline", "b", "--out", "o"]) == vd.EXIT_USAGE


@pytest.mark.skipif(vd.missing_tools() != [], reason="LibreOffice/pdftoppm not installed")
def test_render_real_docx(tmp_path):
    docx = os.environ.get("VISUAL_DOCX")
    if not docx or not os.path.exists(docx):
        pytest.skip("set VISUAL_DOCX to a DOCX (e.g. target/e2e-evidence/service-agreement.ES.docx)")
    pages = vd.render(docx, str(tmp_path / "render"), 50)
    assert len(pages) >= 1
    assert vd.ink_fraction(Image.open(pages[0])) > 0.0005
