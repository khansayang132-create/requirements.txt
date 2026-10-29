"""Unit tests: schemas, timing, pronunciation, script review/revision/locking, subtitles, publishing."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from pydantic import ValidationError

from apex.models import ProductionSpec, SceneSpec, Script, Storyboard
from apex.publishing import DryRunAdapter, Post, PostState
from apex.script_engine import (OpenAICompatibleProvider, ProviderUnavailable, extract_json, lock_script,
                                provider_from_env, review_script, write_script)
from apex.storyboard import build_storyboard
from apex.subtitles import build_srt, build_title_srt, validate_srt
from apex.timing import allocate, fits_target, word_count
from apex.tts import id_number_words, normalize_for_speech

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "money-mistake"


def sample_script() -> Script:
    return Script.model_validate_json((SAMPLE / "script.json").read_text(encoding="utf-8"))


def sample_spec() -> ProductionSpec:
    return ProductionSpec.model_validate_json((SAMPLE / "spec.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- schemas

def test_sample_script_and_spec_validate():
    assert len(sample_script().scenes) == 6
    assert sample_spec().language == "id"


def test_unknown_template_rejected():
    data = json.loads((SAMPLE / "script.json").read_text(encoding="utf-8"))
    data["scenes"][0]["template"] = "spaceship"
    with pytest.raises(ValidationError, match="unknown template"):
        Script.model_validate(data)


def test_duplicate_scene_ids_rejected():
    data = json.loads((SAMPLE / "script.json").read_text(encoding="utf-8"))
    data["scenes"][1]["scene_id"] = "s01"
    with pytest.raises(ValidationError, match="unique"):
        Script.model_validate(data)


def test_scene_spec_duration_must_match_times():
    with pytest.raises(ValidationError):
        SceneSpec(scene_id="s01", scene_order=0, start_time=0, end_time=3, duration=2, narrative_purpose="x",
                  narration_text="x", subtitle_text="x", template="hero_coin", camera_move="static")


def test_storyboard_rejects_gaps():
    a = SceneSpec(scene_id="s01", scene_order=0, start_time=0, end_time=2, duration=2, narrative_purpose="x",
                  narration_text="x", subtitle_text="x", template="hero_coin", camera_move="static")
    b = a.model_copy(update={"scene_id": "s02", "scene_order": 1, "start_time": 2.5, "end_time": 4.5})
    with pytest.raises(ValidationError, match="gap or overlap"):
        Storyboard(script_version="v", fps=24, width=432, height=768, scenes=[a, b])


def test_script_version_ignores_provenance():
    s = sample_script()
    assert s.version_hash == s.model_copy(update={"provenance": "someone else"}).version_hash


# ---------------------------------------------------------------- timing

def test_allocate_snaps_to_frames_and_is_contiguous():
    parts = allocate([1.0, 3.333, 4.9], fps=24)
    assert parts[0] == (0.0, 2.0, 2.0)  # minimum scene length
    for (s0, e0, _), (s1, _, _) in zip(parts, parts[1:]):
        assert s1 == e0
    for _, _, d in parts:
        assert abs(d * 24 - round(d * 24)) < 0.03


def test_fits_target_and_word_count():
    assert fits_target(31.0, 30, 3) and not fits_target(34.0, 30, 3)
    assert word_count("Ada satu kebiasaan kecil.") == 4


def test_storyboard_from_script():
    board = build_storyboard(sample_script(), [3.0, 4.0, 3.5, 5.0, 6.0, 5.5], "9:16", 24)
    assert (board.width, board.height) == (432, 768)
    assert board.scenes[0].transition_in == "fade" and board.scenes[-1].transition_out == "fade"
    assert board.scenes[2].on_screen_text == "Rp750.000 / BULAN"


# ---------------------------------------------------------------- pronunciation

@pytest.mark.parametrize("n,words", [
    (11, "sebelas"), (15, "lima belas"), (100, "seratus"), (115, "seratus lima belas"),
    (1000, "seribu"), (25000, "dua puluh lima ribu"), (750000, "tujuh ratus lima puluh ribu"),
    (9000000, "sembilan juta"), (1250000, "satu juta dua ratus lima puluh ribu")])
def test_indonesian_numbers(n, words):
    assert id_number_words(n) == words


def test_rupiah_normalized_for_speech():
    assert normalize_for_speech("kopi Rp25.000 setiap hari", "id") == "kopi dua puluh lima ribu rupiah setiap hari"
    assert normalize_for_speech("Rp 9.000.000", "id") == "sembilan juta rupiah"
    assert normalize_for_speech("Rp25.000", "en") == "Rp25.000"


@pytest.mark.parametrize("text, spoken", [
    # Indonesian writes decimals with a comma; read as "koma" + digits, the scale before "rupiah".
    ("tabungan Rp1,5 juta", "tabungan satu koma lima juta rupiah"),
    ("Rp 2,25 miliar", "dua koma dua lima miliar rupiah"),
    ("Rp500 ribu", "lima ratus ribu rupiah"),
    ("Rp9 Juta", "sembilan juta rupiah"),
    # Social-media shorthand: rb / k = ribu, jt = juta, written straight after the number.
    ("kopi Rp10rb", "kopi sepuluh ribu rupiah"),
    ("Rp 50k sehari", "lima puluh ribu rupiah sehari"),
    ("Rp1,5jt", "satu koma lima juta rupiah"),
    ("Rp5 kali lipat", "lima rupiah kali lipat"),
    ("bunga 2,5 persen", "bunga dua koma lima persen"),
    ("1.250,75 gram", "seribu dua ratus lima puluh koma tujuh lima gram"),
])
def test_decimal_comma_normalized_for_speech(text, spoken):
    assert normalize_for_speech(text, "id") == spoken


@pytest.mark.parametrize("text, spoken", [
    # "3x sehari" is how scripts write "three times a day"; the x is read as "kali".
    ("minum 3x sehari", "minum tiga kali sehari"),
    ("naik 2X lipat", "naik dua kali lipat"),
    ("4x4 meter", "empat kali empat meter"),
    ("2 x seminggu", "dua kali seminggu"),
    # Not a multiplier: a size like 3xl is left exactly as it was.
    ("ukuran 3xl", "ukuran 3xl"),
])
def test_multiplier_x_normalized_for_speech(text, spoken):
    assert normalize_for_speech(text, "id") == spoken


@pytest.mark.parametrize("text, spoken", [
    # An English decimal point before a scale word ("Rp1.5 juta") is a decimal, read as "koma".
    ("tabungan Rp1.5 juta", "tabungan satu koma lima juta rupiah"),
    ("Rp 2.25 miliar", "dua koma dua lima miliar rupiah"),
    ("Rp1.5jt", "satu koma lima juta rupiah"),
    # Three digits after the dot stay a thousands separator.
    ("Rp1.500 juta", "seribu lima ratus juta rupiah"),
])
def test_rupiah_decimal_point_normalized_for_speech(text, spoken):
    assert normalize_for_speech(text, "id") == spoken


# ---------------------------------------------------------------- script engine

def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Here:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('Sure! {"a": 3} Done.') == {"a": 3}


def test_sample_script_passes_review():
    assert review_script(sample_script(), sample_spec()) == []


def test_review_catches_greeting_stat_and_long_text():
    data = json.loads((SAMPLE / "script.json").read_text(encoding="utf-8"))
    data["scenes"][0]["narration"] = "Halo guys, hari ini aku mau cerita."
    data["scenes"][1]["narration"] = "Sebanyak 73% orang melakukan ini."
    data["scenes"][2]["on_screen_text"] = "INI TEKS YANG TERLALU PANJANG UNTUK LAYAR HP"
    problems = review_script(Script.model_validate(data), sample_spec())
    assert any("greeting" in p for p in problems)
    assert any("percentage" in p for p in problems)
    assert any("40 characters" in p for p in problems)


class FakeProvider:
    name = "fake"

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def _reply(**changes):
    data = json.loads((SAMPLE / "script.json").read_text(encoding="utf-8"))
    data.pop("provenance")
    data["scenes"][0].update(changes)
    return "```json\n" + json.dumps(data, ensure_ascii=False) + "\n```"


def test_write_script_revises_until_review_passes():
    p = FakeProvider([_reply(narration="Halo semuanya, apa kabar?"), _reply()])
    script, log = write_script(sample_spec(), p, max_revisions=2)
    assert [len(x["problems"]) > 0 for x in log] == [True, False]
    assert "Problems:" in p.prompts[1] and "greeting" in p.prompts[1]
    assert script.provenance.startswith("generated by fake")


def test_write_script_respects_revision_limit():
    p = FakeProvider([_reply(narration="Halo semuanya, apa kabar?")])
    _, log = write_script(sample_spec(), p, max_revisions=1)
    assert len(log) == 2 and log[-1]["problems"]


def test_lock_script_reports_changed_scenes(tmp_path):
    s = sample_script()
    first = lock_script(s, tmp_path)
    assert first["previous"] is None and first["scenes_needing_regeneration"] == []
    data = s.model_dump()
    data["scenes"][3]["params"] = {"values": [1, 2, 3]}
    second = lock_script(Script.model_validate(data), tmp_path)
    assert second["previous"] == first["version"]
    assert second["scenes_needing_regeneration"] == ["s04"]
    assert (tmp_path / "scripts" / f"script_{first['version']}.json").exists()


def test_provider_from_env_requires_credentials(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OMNIROUTE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ProviderUnavailable):
        provider_from_env()


def test_openai_compatible_provider_against_local_server():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["auth"] = self.headers.get("authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            out = json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        p = OpenAICompatibleProvider(f"http://127.0.0.1:{srv.server_port}/v1", "k123", "auto")
        assert p.complete("hi") == "hello"
        assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer k123"
        assert seen["body"]["model"] == "auto"
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- subtitles

def test_srt_is_valid_and_inside_scenes():
    board = build_storyboard(sample_script(), [3.0, 4.0, 3.5, 5.0, 6.0, 5.5], "9:16", 24)
    srt = build_srt(board, [3.0, 4.0, 3.5, 5.0, 6.0, 5.5])
    assert validate_srt(srt) == []
    assert validate_srt(build_title_srt(board)) == []
    assert "Rp9 JUTA / TAHUN" in build_title_srt(board)


def test_validate_srt_finds_problems():
    bad = "1\n00:00:02,000 --> 00:00:01,000\nback\n\n3\n00:00:00,500 --> 00:00:03,000\nx\n"
    problems = validate_srt(bad)
    assert any("ends before" in p for p in problems)
    assert any("out of sequence" in p for p in problems)
    assert any("overlaps" in p for p in problems)


# ---------------------------------------------------------------- publishing

class ConfirmingAdapter:
    platform = "test"

    def publish(self, video, metadata):
        return {"confirmed": True, "post_id": "123", "url": "https://example.invalid/123"}


class UnauthorizedAdapter:
    platform = "test"

    def publish(self, video, metadata):
        raise PermissionError("token expired")


def _approved(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    post = Post(v, {"caption": "c"}, "tiktok")
    post.move(PostState.READY_FOR_REVIEW)
    post.move(PostState.APPROVED)
    return post


def test_dry_run_never_marks_published(tmp_path):
    post = _approved(tmp_path)
    post.submit(DryRunAdapter(tmp_path / "pkg"))
    assert post.state == PostState.STATUS_UNKNOWN
    assert (tmp_path / "pkg" / "post.json").exists()


def test_only_confirmation_publishes(tmp_path):
    post = _approved(tmp_path)
    post.submit(ConfirmingAdapter())
    assert post.state == PostState.PUBLISHED and post.result["post_id"] == "123"


def test_expired_token_requires_authorization(tmp_path):
    post = _approved(tmp_path)
    post.submit(UnauthorizedAdapter())
    assert post.state == PostState.REQUIRES_AUTHORIZATION


def test_cannot_skip_review(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    with pytest.raises(ValueError):
        Post(v, {}, "tiktok").move(PostState.SUBMISSION_IN_PROGRESS)
