"""Metadata generation and validation limits."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from conftest import ROOT, run_script

from src.config import load_settings, load_yaml_file
from src.metadata import fit_tags, generate, to_hashtag, truncate_words
from src.validators import (
    tags_api_length,
    validate_description,
    validate_metadata,
    validate_schedule,
    validate_tags,
    validate_title,
)

TEMPLATES = load_settings()["metadata"]


def test_sample_topic_generates_valid_metadata():
    meta = generate(load_yaml_file(ROOT / "data/topics/sample_topic.yaml"), TEMPLATES)
    assert meta["validation"]["ok"], meta["validation"]
    assert 0 < len(meta["title"]) <= 100
    assert [t.lower() for t in meta["tags"]].count("nikah beda negara") == 1
    assert any("duplicate" in n for n in meta["notes"])
    assert meta["hashtags"][:2] == ["#NikahBedaNegara", "#IndonesiaPakistan"]
    assert meta["category_id"] == "22" and meta["category_reason"].startswith("matched keywords")
    assert "0:00 Pembuka" in meta["description"]
    assert "not guaranteed" in meta["disclaimer"]


def test_generation_is_deterministic():
    topic = load_yaml_file(ROOT / "data/topics/sample_topic.yaml")
    assert generate(topic, TEMPLATES) == generate(topic, TEMPLATES)


def test_long_title_is_cut_at_word_boundary():
    topic = {"hook": "kata " * 40, "keywords": ["a"]}
    meta = generate(topic, TEMPLATES)
    assert len(meta["title"]) <= 100 and meta["title"].endswith("…")
    assert not meta["title"][:-1].endswith(" ")


def test_invalid_characters_are_removed():
    meta = generate({"title": "Kisah <nyata> kami", "summary": "a <b> c", "keywords": ["x<y>"]}, TEMPLATES)
    assert "<" not in meta["title"] and ">" not in meta["title"]
    assert "<" not in meta["description"] and all("<" not in t for t in meta["tags"])
    assert meta["validation"]["ok"]


def test_tags_fit_500_character_api_limit():
    keywords = [f"keyword number {i} with several words" for i in range(40)]
    kept, dropped = fit_tags(keywords, max_count=100)
    assert tags_api_length(kept) <= 500 and dropped
    meta = generate({"topic": "x", "keywords": keywords}, {**TEMPLATES, "max_tags": 100})
    assert meta["validation"]["info"]["tags_api_length"] <= 500
    assert any("dropped tags" in n for n in meta["notes"])


def test_explicit_category_wins_and_default_applies():
    assert generate({"topic": "x", "category_id": 27}, TEMPLATES)["category_id"] == "27"
    assert generate({"topic": "zzz"}, TEMPLATES, default_category="24")["category_id"] == "24"


def test_hashtag_formatting():
    assert to_hashtag("nikah beda negara") == "#NikahBedaNegara"
    assert to_hashtag("#FYP".lstrip("#")) == "#FYP"
    assert truncate_words("one two three", 9) == "one two…"


# -------------------------------------------------------------- validators ------
def test_title_limits():
    assert validate_title("x" * 100).ok
    assert not validate_title("x" * 101).ok
    assert not validate_title("   ").ok
    assert not validate_title(None).ok
    assert not validate_title("a > b").ok


def test_description_counts_bytes_not_characters():
    assert validate_description("a" * 5000).ok
    emoji = "💞" * 1251  # 4 bytes each = 5004 bytes, 1251 characters
    r = validate_description(emoji)
    assert not r.ok and "5004 bytes" in r.errors[0]
    assert not validate_description("use <html>").ok


def test_tag_rules():
    assert tags_api_length(["a b", "c"]) == len('"a b",c')
    assert not validate_tags(["Nikah", "nikah"]).ok  # duplicate keyword, case-insensitive
    assert not validate_tags(["a,b"]).ok
    assert not validate_tags([""]).ok
    assert validate_tags(["ok", "also ok"]).ok


def test_schedule_rules():
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert validate_schedule(future, "private").ok
    assert not validate_schedule(future, "public").ok  # publishAt needs private
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert not validate_schedule(past, "private").ok
    assert not validate_schedule("2030-01-01T10:00:00", "private").ok  # no timezone
    assert validate_schedule("2030-01-01T10:00:00+07:00", "private").info["publish_at_utc"] == "2030-01-01T03:00:00Z"


def test_made_for_kids_must_be_explicit():
    base = {"title": "t", "description": "d", "tags": [], "category_id": "22", "privacy": "private"}
    assert not validate_metadata({**base, "made_for_kids": None}).ok
    assert validate_metadata({**base, "made_for_kids": False}).ok


def test_empty_metadata_is_reported():
    r = validate_metadata({})
    assert any(e.startswith("title") for e in r.errors)
    assert any(e.startswith("categoryId") for e in r.errors)
    assert any(e.startswith("privacyStatus") for e in r.errors)


# --------------------------------------------------------------------- CLI ------
def test_generate_metadata_cli_writes_file(tmp_path):
    out = tmp_path / "meta.json"
    r = run_script("skills/youtube-metadata/scripts/generate_metadata.py", "--topic", "data/topics/sample_topic.yaml", "--out", str(out), "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text())["title"] == json.loads(r.stdout)["title"]


def test_validate_only_cli_fails_on_bad_metadata(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("title: ''\ntags: [a, A]\n")
    r = run_script("skills/youtube-metadata/scripts/generate_metadata.py", "--validate-only", str(bad), "--json")
    assert r.returncode == 5
    errors = json.loads(r.stdout)["errors"]
    assert any("title" in e for e in errors) and any("duplicate" in e for e in errors)
