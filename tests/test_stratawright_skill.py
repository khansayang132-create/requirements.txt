"""Tests for the stratawright-daw skill wrapper (.claude/skills/stratawright-daw/scripts/daw.py).

The real DAW isn't available in CI, so a fake server on a temp UNIX socket answers in
the exact formats of Stratawright's result_formatter.cpp (@ 35008ae).
"""
import importlib.util
import json
import os
import socket
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude/skills/stratawright-daw"
spec = importlib.util.spec_from_file_location("daw", SKILL / "scripts/daw.py")
daw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daw)


class FakeDaw:
    """Serial accept loop like ipc_server.cpp: read one line, write the reply, close."""

    def __init__(self, handler):
        self.dir = tempfile.mkdtemp(dir="/tmp")
        self.path = os.path.join(self.dir, "s.sock")
        self.handler = handler
        self.received = []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        self.srv.listen(5)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            with c:
                line = c.recv(4096).decode()
                self.received.append(line)
                c.sendall(self.handler(line.strip()).encode())

    def close(self):
        self.srv.close()
        os.unlink(self.path)
        os.rmdir(self.dir)


@pytest.fixture
def fake():
    servers = []

    def make(handler):
        s = FakeDaw(handler)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def test_server_error_is_failure_with_real_code(fake):
    s = fake(lambda cmd: 'ERROR 72 ENTITY_NOT_FOUND "Track 9 not found."\n')
    r = daw.Daw(s.path).call(["track", "inspect", "--track", "9"])
    assert (r["ok"], r["code"], r["symbol"]) == (False, 72, "ENTITY_NOT_FOUND")
    assert r["message"] == "Track 9 not found."


def test_main_exit_code_matches_protocol_code(fake, capsys):
    s = fake(lambda cmd: 'ERROR 70 INVALID_ARGS "Missing required --track argument."\n')
    assert daw.main(["--socket", s.path, "--journal", "", "run", "track", "set-gain", "--db", "-3"]) == 70


def test_no_daw_is_71(tmp_path):
    r = daw.Daw(str(tmp_path / "missing.sock")).call(["status"])
    assert (r["ok"], r["code"]) == (False, 71)


def test_wire_format_matches_client_and_requests_json(fake):
    s = fake(lambda cmd: "OK TRACK_CREATED\n")
    daw.Daw(s.path).call(["track", "create", "--name", "Vox Lead", "--type", "audio", "--color", "yellow"])
    assert s.received[0] == 'track create --name "Vox Lead" --type audio --color yellow --format json\n'


def test_export_keeps_format_as_codec_and_parses_tsv(fake):
    s = fake(lambda cmd: "bit_depth\tdestination\tjob_id\n24\t/tmp/m.wav\t3\n")
    r = daw.Daw(s.path).call(["export", "master", "--output", "/tmp/m.wav", "--format", "wav"])
    assert "--format json" not in s.received[0]
    assert r["fields"] == {"bit_depth": 24, "destination": "/tmp/m.wav", "job_id": 3}


def test_long_reply_is_not_truncated(fake):
    rows = [{"ID": str(i), "NAME": f"Plugin number {i} with a long name"} for i in range(400)]
    payload = "[" + ",".join("{" + ",".join(f'"{k}":"{v}"' for k, v in r.items()) + "}" for r in rows) + "]\n"
    assert len(payload) > 4096
    s = fake(lambda cmd: payload)
    r = daw.Daw(s.path).call(["plugin", "list"])
    assert len(r["rows"]) == 400 and r["rows"][-1]["ID"] == 399


def test_empty_list_prints_ok_symbol_even_for_json():
    r = daw.parse_reply("OK CLIP_LIST\n")
    assert r["ok"] and r["rows"] == [] and r["symbol"] == "CLIP_LIST"


def test_values_are_typed():
    r = daw.parse_reply('{"GAIN_DB":"-3.5","ID":"2","MUTE":"false","NAME":"Kick"}\n')
    assert r["fields"] == {"GAIN_DB": -3.5, "ID": 2, "MUTE": False, "NAME": "Kick"}


def test_quote_in_argument_is_refused_before_sending(fake):
    s = fake(lambda cmd: "OK X\n")
    with pytest.raises(ValueError):
        daw.Daw(s.path).call(["track", "create", "--name", 'Bad "name"', "--type", "audio", "--color", "red"])
    assert s.received == []


def test_dry_run_sends_no_mutation_but_still_reads(fake):
    s = fake(lambda cmd: "[]\n")
    d = daw.Daw(s.path, dry_run=True)
    r = d.call(["track", "delete", "--track", "4"])
    assert r["symbol"] == "DRY_RUN" and s.received == []
    d.call(["track", "list"])
    assert len(s.received) == 1


def test_mutations_are_journaled_reads_are_not(fake, tmp_path):
    s = fake(lambda cmd: "OK X\n")
    j = tmp_path / "j.jsonl"
    d = daw.Daw(s.path, journal=str(j))
    d.call(["track", "list"])
    d.call(["analyze", "loudness", "--track", "1"])
    d.call(["track", "set-gain", "--track", "1", "--db", "-2"])
    lines = [json.loads(x) for x in j.read_text().splitlines()]
    assert len(lines) == 1 and lines[0]["command"].startswith("track set-gain")


def test_batch_stops_at_first_error(fake, tmp_path, capsys):
    def h(cmd):
        return 'ERROR 72 ENTITY_NOT_FOUND "nope"\n' if cmd.startswith("plugin add") else "OK X\n"
    s = fake(h)
    plan = tmp_path / "plan.txt"
    plan.write_text("# setup\ntransport stop\ndaw-cli plugin add --track 1 --name \"Pro Q\"\ntrack auto-color\n")
    code = daw.main(["--socket", s.path, "--journal", "", "batch", str(plan)])
    assert code == 72
    assert [c.split()[0] for c in s.received] == ["transport", "plugin"]


def test_expand_range_matches_server_grammar():
    assert daw.expand_range("1..4,7,9..10") == [1, 2, 3, 4, 7, 9, 10]


@pytest.mark.parametrize("peak,crest,action,offset,limited_by", [
    (-12.0, 12.0, "apply", 6.0, None),               # est. RMS -24 -> +6 dB, peak lands exactly on -6
    (-20.0, 4.0, "apply", 6.0, None),                # dense source, plenty of peak room
    (-3.0, 20.0, "apply", -3.0, "peak_ceiling"),     # wants +5 but peak is already over the ceiling
    (-10.0, 8.0, "none", 0.0, None),                 # already at target
])
def test_plan_gain(peak, crest, action, offset, limited_by):
    p = daw.plan_gain(peak, crest, -18.0, -6.0, 24.0)
    assert (p["action"], p["offset_db"], p["limited_by"]) == (action, offset, limited_by)
    assert peak + p["offset_db"] <= -6.0 or p["offset_db"] < 0


def test_plan_gain_skips_silence():
    assert daw.plan_gain(-120.0, 0.0, -18.0, -6.0, 24.0)["action"] == "skip"


def test_plan_gain_ceiling_limits_spiky_source():
    p = daw.plan_gain(peak_dbfs=-8.0, crest_db=20.0, target_rms=-18.0, ceiling=-6.0, max_move=24.0)
    assert p["offset_db"] == 2.0 and p["limited_by"] == "peak_ceiling"


def test_plan_gain_refuses_huge_moves():
    p = daw.plan_gain(peak_dbfs=-70.0, crest_db=10.0, target_rms=-18.0, ceiling=-6.0, max_move=24.0)
    assert p["action"] == "skip"


def test_gain_stage_applies_clip_gain_and_verifies(fake):
    state = {"clip_db": 0.0}

    def h(cmd):
        if cmd.startswith("analyze loudness"):
            return json.dumps({"SAMPLE_PEAK_DBFS": f"{-12.0 + state['clip_db']}", "CREST_FACTOR_DB": "12.0",
                               "INTEGRATED_LUFS": "-26.0"}) + "\n"
        if cmd.startswith("clip list"):
            return '[{"CLIP_ID":"5","GAIN_DB":"0.000000","TRACK_ID":"1","TYPE":"AUDIO"}]\n'
        if cmd.startswith("clip set-gain"):
            state["clip_db"] = float(cmd.split("--db ")[1].split()[0])
            return '{"clip_id":"5"}\n'
        return "OK X\n"

    s = fake(h)
    rep = daw.gain_stage(daw.Daw(s.path), "1", -18.0, -6.0, "clip", True, 24.0)
    t = rep["tracks"][0]
    assert t["offset_db"] == 6.0 and t["applied"] is True and t["verified"] is True
    assert any(c.startswith("clip set-gain --track 1 --clip 5 --db 6.0") for c in s.received)
    assert rep["ok"]


def test_gain_stage_flags_unverified_change(fake):
    def h(cmd):  # measurement never moves: e.g. the gain didn't apply
        if cmd.startswith("analyze loudness"):
            return '{"CREST_FACTOR_DB":"12.0","SAMPLE_PEAK_DBFS":"-12.0"}\n'
        if cmd.startswith("track inspect"):
            return '{"GAIN_DB":"-2.0","ID":"1"}\n'
        return "OK X\n"

    s = fake(h)
    rep = daw.gain_stage(daw.Daw(s.path), "1", -18.0, -6.0, "fader", True, 24.0)
    assert not rep["ok"] and rep["unverified_tracks"] == [1]
    assert any(c.startswith("track set-gain --track 1 --db 4.0") for c in s.received)


def test_skill_frontmatter_and_links():
    text = (SKILL / "SKILL.md").read_text()
    assert text.startswith("---\nname: stratawright-daw\n")
    assert len(text.splitlines()) < 500
    for ref in ("references/commands.md", "references/workflows.md", "references/errors.md",
                "references/source-notes.md"):
        assert ref in text and (SKILL / ref).is_file()
    assert "file:///" not in text
