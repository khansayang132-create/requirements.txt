import pytest

from hvlib import core


def test_illegal_transition_and_missing_evidence(tmp_path):
    m = core.Manifest(tmp_path / "manifest.json")
    with pytest.raises(core.TransitionError, match="ILLEGAL_TRANSITION"):
        m.advance("MODELING", [])
    with pytest.raises(core.TransitionError, match="EVIDENCE_MISSING"):
        m.advance("RESEARCH", [tmp_path / "nope.md"])
    (tmp_path / "empty.md").write_text("")
    with pytest.raises(core.TransitionError, match="EVIDENCE_MISSING"):
        m.advance("RESEARCH", [tmp_path / "empty.md"])


def test_acceptance_criteria_and_history(tmp_path):
    ev = tmp_path / "ev.md"
    ev.write_text("x")
    m = core.Manifest(tmp_path / "manifest.json")
    m.advance("RESEARCH", [ev])
    with pytest.raises(core.TransitionError, match="ACCEPTANCE_FAILED"):
        m.advance("DESIGN", [ev], criteria={"five_characters": False})
    m.advance("DESIGN", [ev], criteria={"five_characters": True})
    assert m.state == "DESIGN" and m.data["history"][-1]["evidence"][0]["sha256"] == core.sha256(ev)
    assert core.Manifest(tmp_path / "manifest.json").state == "DESIGN"        # persisted


def test_blocked_recovers_only_to_blocked_state(tmp_path):
    ev = tmp_path / "ev.md"
    ev.write_text("x")
    m = core.Manifest(tmp_path / "manifest.json")
    m.block("no blender", "RESEARCH")
    with pytest.raises(core.TransitionError):
        m.advance("DESIGN", [ev])
    m.advance("RESEARCH", [ev])
    assert m.state == "RESEARCH"


def test_two_agents_cannot_own_one_asset_and_tampering_is_detected(tmp_path):
    f = tmp_path / "a.blend"
    f.write_bytes(b"BLENDER-v1")
    m = core.Manifest(tmp_path / "manifest.json")
    m.register("blend", "CHAR-HUM-001", f, "character-modeling-engineer")
    with pytest.raises(core.TransitionError, match="OWNERSHIP"):
        m.register("blend", "CHAR-HUM-001", f, "film-editor")
    assert m.verify_assets() == []
    f.write_bytes(b"BLENDER-v2")
    assert m.verify_assets() == ["blend:CHAR-HUM-001"]
