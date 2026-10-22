"""Tests for vision/segmenter.py on synthetic pages: no real documents, deterministic."""
import importlib.util
import json
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("segmenter", os.path.join(HERE, "..", "segmenter.py"))
seg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seg)

W, H = 850, 1100  # Letter at 100 dpi


def page(tmp_path, name="page.png", stamp=False, signature=False, text=True):
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    if text:  # black "text lines": must never be reported
        for i in range(12):
            d.rectangle((80, 100 + i * 40, 700, 112 + i * 40), fill=(20, 20, 20))
    if stamp:  # red round stamp, bottom right
        d.ellipse((560, 760, 760, 960), outline=(200, 30, 40), width=10)
        d.text((610, 850), "PAID", fill=(200, 30, 40))
        d.ellipse((600, 800, 720, 920), outline=(200, 30, 40), width=6)
    if signature:  # blue wavy stroke, bottom left
        pts = [(100 + x, 900 + int(18 * ((x // 15) % 2 * 2 - 1))) for x in range(0, 300, 15)]
        d.line(pts, fill=(30, 50, 190), width=3)
    p = tmp_path / name
    img.save(p)
    return str(p)


def run(tmp_path, img_path, *extra):
    out = tmp_path / "out"
    code = seg.main(["--input", img_path, "--out-dir", str(out), *extra])
    report = json.load(open(out / "artifacts.json")) if (out / "artifacts.json").exists() else None
    return code, report, out


def test_black_text_only_has_no_artifacts(tmp_path):
    code, report, out = run(tmp_path, page(tmp_path))
    assert code == 0
    assert report["artifacts"] == []
    assert report["schemaVersion"] == 1
    assert report["image"] == {"width": W, "height": H}


def test_red_stamp_is_found_where_it_is(tmp_path):
    code, report, _ = run(tmp_path, page(tmp_path, stamp=True))
    assert code == 0
    stamps = [a for a in report["artifacts"] if a["kind"] == "stamp"]
    assert len(stamps) == 1, report
    x, y, w, h = stamps[0]["bbox_norm"]
    assert abs(x - 560 / W) < 0.03 and abs(y - 760 / H) < 0.03
    assert abs(w - 200 / W) < 0.04 and abs(h - 200 / H) < 0.04


def test_blue_signature_is_classified_as_signature(tmp_path):
    code, report, _ = run(tmp_path, page(tmp_path, signature=True))
    kinds = [a["kind"] for a in report["artifacts"]]
    assert code == 0
    assert kinds == ["signature"], report


def test_both_are_found_and_sorted_top_to_bottom(tmp_path):
    _, report, _ = run(tmp_path, page(tmp_path, stamp=True, signature=True))
    assert sorted(a["kind"] for a in report["artifacts"]) == ["signature", "stamp"]
    ys = [a["bbox_norm"][1] for a in report["artifacts"]]
    assert ys == sorted(ys)


def test_mask_and_cleaned_page(tmp_path):
    _, report, out = run(tmp_path, page(tmp_path, stamp=True))
    mask = Image.open(out / "mask.png")
    cleaned = Image.open(out / "cleaned.png").convert("RGB")
    assert mask.size == (W, H) and mask.mode == "L"
    assert mask.getpixel((560 + 5, 860)) == 255  # stamp ring
    assert mask.getpixel((300, 106)) == 0  # black text line untouched
    assert cleaned.getpixel((560 + 5, 860)) == (255, 255, 255)  # stamp removed
    assert cleaned.getpixel((300, 106)) == (20, 20, 20)  # text kept for OCR


def test_deterministic(tmp_path):
    p = page(tmp_path, stamp=True, signature=True)
    _, a, _ = run(tmp_path, p)
    _, b, _ = run(tmp_path, p)
    assert a == b


def test_unreadable_input_is_exit_3(tmp_path):
    bad = tmp_path / "not-an-image.png"
    bad.write_text("hello")
    assert seg.main(["--input", str(bad), "--out-dir", str(tmp_path / "o")]) == seg.EXIT_INPUT
    assert seg.main(["--input", str(tmp_path / "missing.png"), "--out-dir", str(tmp_path / "o")]) == seg.EXIT_INPUT
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (4, 4), "white").save(tiny)
    assert seg.main(["--input", str(tiny), "--out-dir", str(tmp_path / "o")]) == seg.EXIT_INPUT


def test_usage_errors_are_exit_2(tmp_path):
    assert seg.main([]) == seg.EXIT_USAGE
    assert seg.main(["--input", "x", "--out-dir", "y", "--min-area", "0.9"]) == seg.EXIT_USAGE


def test_greyscale_scan_input_works(tmp_path):
    p = tmp_path / "grey.png"
    Image.open(page(tmp_path, stamp=True)).convert("L").save(p)
    code, report, _ = run(tmp_path, str(p))
    assert code == 0
    assert report["artifacts"] == [], "no colour information means no coloured-ink artifacts"


def test_cleaned_page_has_no_coloured_residue(tmp_path):
    # Anti-aliased edges of thin stamp text once survived cleaning (20 faint red pixels).
    import numpy as np
    _, _, out = run(tmp_path, page(tmp_path, stamp=True, signature=True))
    hsv = np.asarray(Image.open(out / "cleaned.png").convert("HSV"))
    assert int(((hsv[..., 1] >= 35) & (hsv[..., 2] < 245)).sum()) == 0
