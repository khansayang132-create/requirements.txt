"""Thumbnail validation (never modifies the file) and the thumbnails.set path."""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from conftest import SAMPLE_THUMB, make_client, ok, run_script
from PIL import Image

from src.validators import THUMB_MAX_BYTES, validate_thumbnail


def img(path, size=(1280, 720), fmt="JPEG", noise=False):
    if noise:
        im = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    else:
        im = Image.new("RGB", size, (200, 30, 30))
    im.save(path, fmt)
    return path


def test_sample_thumbnail_passes():
    r = validate_thumbnail(SAMPLE_THUMB)
    assert r.ok and not r.warnings
    assert r.info["format"] == "JPEG" and (r.info["width"], r.info["height"]) == (1280, 720)
    assert r.info["mimetype"] == "image/jpeg"


def test_png_supported(tmp_path):
    r = validate_thumbnail(img(tmp_path / "t.png", fmt="PNG"))
    assert r.ok and r.info["mimetype"] == "image/png"


def test_over_2mb_is_rejected(tmp_path):
    p = img(tmp_path / "big.png", fmt="PNG", noise=True)
    assert p.stat().st_size > THUMB_MAX_BYTES
    r = validate_thumbnail(p)
    assert not r.ok and any("2 MB" in e for e in r.errors)


def test_too_narrow_is_an_error(tmp_path):
    r = validate_thumbnail(img(tmp_path / "small.jpg", size=(320, 180)))
    assert not r.ok and any("minimum of 640" in e for e in r.errors)


def test_wrong_aspect_is_warning_or_error_in_strict(tmp_path):
    p = img(tmp_path / "square.jpg", size=(1000, 1000))
    loose = validate_thumbnail(p)
    assert loose.ok and any("16:9" in w for w in loose.warnings)
    strict = validate_thumbnail(p, strict=True)
    assert not strict.ok and any("16:9" in e for e in strict.errors)


def test_16_9_but_not_1280_is_warning(tmp_path):
    r = validate_thumbnail(img(tmp_path / "hd.jpg", size=(1920, 1080)))
    assert r.ok and any("1280x720" in w for w in r.warnings)


def test_gif_rejected(tmp_path):
    r = validate_thumbnail(img(tmp_path / "t.gif", fmt="GIF"))
    assert not r.ok and any("JPEG or PNG" in e for e in r.errors)


def test_corrupt_and_fake_images_rejected(tmp_path):
    good = img(tmp_path / "good.jpg")
    truncated = tmp_path / "trunc.jpg"
    truncated.write_bytes(good.read_bytes()[:200])
    assert not validate_thumbnail(truncated).ok
    fake = tmp_path / "fake.jpg"
    fake.write_text("not an image")
    assert not validate_thumbnail(fake).ok
    assert not validate_thumbnail(tmp_path / "missing.jpg").ok


def test_extension_mismatch_warns(tmp_path):
    p = tmp_path / "actually_png.jpg"
    Image.new("RGB", (1280, 720)).save(p, "PNG")
    r = validate_thumbnail(p)
    assert r.ok and any("does not match" in w for w in r.warnings)


def test_validation_never_modifies_the_image(tmp_path):
    p = img(tmp_path / "x.jpg", size=(1000, 1000))
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    validate_thumbnail(p, strict=True)
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before


def test_set_thumbnail_sends_media_to_official_endpoint(rt):
    client, http = make_client(rt, [ok({"items": [{"default": {"url": "https://i.ytimg.com/x.jpg"}}]})])
    resp = client.set_thumbnail("VID123", SAMPLE_THUMB, "image/jpeg")
    assert resp["items"]
    req = http.requests[0]
    assert req["method"] == "POST" and "/upload/youtube/v3/thumbnails/set" in req["uri"] and "videoId=VID123" in req["uri"]
    assert rt.quota.report()["buckets"]["data_api"]["used_estimate"] == 50


# --------------------------------------------------------------------- CLI ------
def test_cli_reports_and_exit_codes(tmp_path):
    bad = img(tmp_path / "small.jpg", size=(320, 180))
    r = run_script("skills/youtube-thumbnail/scripts/validate_thumbnail.py", str(SAMPLE_THUMB), str(bad), "--json")
    assert r.returncode == 5
    data = json.loads(r.stdout)
    assert [x["ok"] for x in data["reports"]] == [True, False]


@pytest.mark.parametrize("flags,code", [([], 2), (["--dry-run"], 0), (["--dry-run", "--confirm"], 0)])
def test_cli_upload_needs_confirmation(flags, code):
    r = run_script("skills/youtube-thumbnail/scripts/validate_thumbnail.py", str(SAMPLE_THUMB), "--upload", "--video-id", "VID", *flags)
    assert r.returncode == code, r.stderr
    if code == 0:
        assert json.loads(r.stdout)["mode"] == "dry_run"
    else:
        assert "--confirm" in r.stderr
