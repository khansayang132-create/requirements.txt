import struct
import zlib

from hvlib import media, story


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _png():
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", b"\0" * 13) + _chunk(b"IDAT", b"\0") + _chunk(b"IEND", b"")


def test_png_integrity(tmp_path):
    good = tmp_path / "0001.png"
    good.write_bytes(_png())
    bad = tmp_path / "0002.png"
    data = bytearray(_png())
    data[-6] ^= 0xFF
    bad.write_bytes(bytes(data))
    (tmp_path / "0003.png").write_bytes(_png()[:-5])
    assert media.png_ok(good) == (True, "ok")
    assert media.png_ok(bad)[1] == "crc_mismatch"
    scan = media.scan_frames(tmp_path, 1, 4)
    assert scan == {"missing": [4], "corrupt": [2, 3], "valid": 1}


def test_screenplay_validation():
    sp = {"title": "t", "logline": "l", "audience": "a", "genre": "g", "theme": "t", "motivations": {"A": "x"}, "conflict": "c",
          "emotional_progression": ["a"], "ending": "e",
          "scenes": [{"scene_id": "S1", "heading": "h", "purpose": " ", "location": "park", "characters": ["A", "Z"],
                      "lines": [{"line_id": "L1", "character_id": "A", "text": "hi"}, {"line_id": "L1", "character_id": "B", "text": "x " * 20}]}]}
    errs = " | ".join(story.validate_screenplay(sp, {"A"}))
    for needle in ("narrative purpose", "unknown character Z", "duplicate line id", "unknown speaker B", "longer than 16 words"):
        assert needle in errs


def test_storyboard_needs_every_field_and_approval():
    shot = {k: "x" for k in story.SHOT_FIELDS} | {"duration": 2.0, "character_ids": ["A"], "dialogue": [], "sound_effects": []}
    sb = {"scene_ids": ["S1", "S2"], "shots": [shot | {"scene_id": "S1"}, shot | {"scene_id": "S2", "lens": ""}]}
    errs = story.validate_storyboard(sb)
    assert any("not approved" in e for e in errs) and any("missing lens" in e for e in errs)
    sb["approved"] = True
    sb["shots"][1]["lens"] = "35mm"
    assert story.validate_storyboard(sb) == []
