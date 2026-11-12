from dhfactory.pipeline.analyze import split_scenes
from dhfactory.state import CharacterSpec, ProductionState


def test_scene_split_and_estimate():
    scenes = split_scenes("Hello there. I am a presenter made for a test. This sentence is the third one and it is long enough.")
    assert [s.index for s in scenes] == list(range(len(scenes)))
    assert all(s.words <= 20 for s in scenes)
    assert abs(sum(s.est_seconds for s in scenes) - sum(s.words for s in scenes) / 2.6) < 0.1


def test_empty_script_rejected():
    import pytest

    with pytest.raises(ValueError):
        split_scenes("   ")


def test_state_round_trip(tmp_path):
    s = ProductionState(job_id="j", script="Hi.")
    s.character = CharacterSpec(character_id="c", name="N", age_range="30s", appearance="a", face="f", hair="h", skin="s", clothing="c",
                                expression="e", voice_style="v")
    p = tmp_path / "state.json"
    s.save(p)
    assert ProductionState.load(p) == s
    assert "N, 30s" in s.character.anchor()
