"""V3 behaviour: owner files untouched, identity locks, spend gate, blocking, resume, originality. No network, no spend."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from cartoon_studio import bible
from cartoon_studio.agents.team import AgentResult, Context, VideoGenerationEngineerAgent
from cartoon_studio.config import Settings
from cartoon_studio.errors import ConsistencyError, ProviderNotConfigured, SpendNotApproved
from cartoon_studio.generators.importer import import_legacy, pick_bodies
from cartoon_studio.generators.originality import check_name, check_words
from cartoon_studio.generators.universe import make_universe
from cartoon_studio.media.probe import probe_video
from cartoon_studio.pipeline import STEPS, run_graph
from cartoon_studio.state import ProductionState, StepRecord

ROOT = Path(__file__).parents[1]


@pytest.fixture
def mosslight(tmp_path):
    for sub in ("universes/mosslight-valley", "stories/mosslight-valley"):
        shutil.copytree(ROOT / sub, tmp_path / sub)
    for cid in ("pipkin", "brindle", "morrow", "tilli", "oakley"):
        (tmp_path / "character-bibles" / cid).mkdir(parents=True)
        shutil.copyfile(ROOT / "character-bibles" / cid / "character.json", tmp_path / "character-bibles" / cid / "character.json")
    return tmp_path


def test_import_keeps_owner_files_and_maps_unique_bodies(mosslight):
    before = {p: p.read_bytes() for p in mosslight.rglob("*.json")}
    u = import_legacy(mosslight, "mosslight-valley", {"Mossy creek": 1, "Fernbridge clearing": 1})
    assert {p: p.read_bytes() for p in mosslight.rglob("*.json")} == before
    bodies = [c.visual.engine_body for c in u.characters]
    assert sorted(bodies) == ["bear", "bunny", "cat", "duck", "elephant"]
    assert u.places == {"pond": "Mossy creek", "meadow": "Fernbridge clearing"}
    pip = next(c for c in u.characters if c.character_id == "pipkin")
    assert pip.identity.species == "moss rabbit" and pip.visual.engine_body == "bunny"
    assert pip.source["v0_3_reference_hash"] and pip.source["character_json_sha256"]
    assert all("no" in w for w in u.originality["warnings"])        # stand-in bodies are disclosed, not hidden


def test_pick_bodies_never_repeats():
    assert pick_bodies(["fox", "fox", "fox", "fox", "fox"]) == ["cat", "bunny", "elephant", "duck", "bear"]


def _fake_bible(root: Path, cid: str) -> None:
    d = root / "character-bibles" / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "character.json").write_text(json.dumps({"id": cid}))
    for f in bible.FILES:
        (d / f).write_bytes(f.encode())
    (d / "bible.json").write_text(json.dumps({"reference_sha256": {f: bible.sha256(d / f) for f in bible.FILES},
                                              "character_json_sha256": bible.sha256(d / "character.json")}))


def test_bible_lock_detects_changed_image_and_changed_identity(tmp_path):
    _fake_bible(tmp_path, "x")
    locked = bible.verify(tmp_path, "x")
    (tmp_path / "character-bibles/x/pose_sheet.png").write_bytes(b"edited")
    with pytest.raises(ConsistencyError, match="pose_sheet.png changed"):
        bible.verify(tmp_path, "x", locked)
    _fake_bible(tmp_path, "y")
    (tmp_path / "character-bibles/y/character.json").write_text('{"id": "y", "species": "changed"}')
    with pytest.raises(ConsistencyError, match="character.json changed"):
        bible.verify(tmp_path, "y")
    with pytest.raises(ConsistencyError, match="no character bible"):
        bible.verify(tmp_path, "missing")


class PaidFake:
    name, paid = "fakevideo", True

    def __init__(self):
        self.calls = 0

    def key(self):
        return "k"

    def estimate_usd(self, capability, amount):
        return 0.5

    def image_to_video(self, image, prompt, out, duration, resume_job_id):
        self.calls += 1
        return {"job_id": "job-1", "video": str(out)}


def test_paid_provider_needs_approve_spend(tmp_path):
    fake = PaidFake()
    s = Settings()
    s.cs_workspace = tmp_path
    agent = VideoGenerationEngineerAgent(Context(s, {"fakevideo": fake}))
    st = ProductionState(job_id="j", universe_id="u", episode_id="e", video_provider="fakevideo")
    with pytest.raises(SpendNotApproved):
        asyncio.run(agent.run(st))
    assert fake.calls == 0


def test_spend_cap_is_enforced(tmp_path):
    s = Settings()
    s.cs_workspace, s.cs_max_spend_usd = tmp_path, 0.1
    agent = VideoGenerationEngineerAgent(Context(s))
    st = ProductionState(job_id="j", universe_id="u", spend_approved=True)
    with pytest.raises(SpendNotApproved, match="CS_MAX_SPEND_USD"):
        agent.authorize(st, PaidFake(), "video", 5)


class Fake:
    def __init__(self, fail=None):
        self.fail, self.calls = fail, []

    def __getattr__(self, method):
        async def f(state):
            self.calls.append(method)
            if self.fail:
                raise self.fail
            return AgentResult(status="success")
        return f


def test_graph_blocks_dependents_and_resumes_without_rerunning(tmp_path):
    names = {s.agent for s in STEPS}
    agents = {n: Fake() for n in names}
    agents["voice-sound-engineer"] = Fake(ProviderNotConfigured("elevenlabs", "set ELEVENLABS_API_KEY"))
    st = ProductionState(job_id="j", universe_id="u", episode_id="e")
    asyncio.run(run_graph(st, agents, lambda s: None))
    assert st.steps["07_voices"].status == "blocked"
    assert st.steps["08_animation"].status == "blocked" and "07_voices" in st.steps["08_animation"].detail
    assert st.steps["09_external_video_scenes"].status == "success"     # independent branch still ran
    first = len(agents["creative-director"].calls)
    agents["voice-sound-engineer"] = Fake()
    asyncio.run(run_graph(st, agents, lambda s: None))
    assert len(agents["creative-director"].calls) == first              # finished steps are not repeated
    assert all(v.status == "success" for v in st.steps.values())


def test_missing_credentials_are_blocked_not_fallback(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for k in ("HF_KEY", "HIGGSFIELD_API_KEY", "HF_API_KEY", "HF_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    from cartoon_studio.providers import get_provider

    with pytest.raises(ProviderNotConfigured):
        get_provider("higgsfield", Settings()).key()
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "abc")          # the v0.3 variable name is accepted
    assert get_provider("higgsfield", Settings()).key() == "abc"


def test_generated_universe_is_deterministic_and_original():
    a, b = make_universe("tiny friends in a valley", "7"), make_universe("tiny friends in a valley", "7")
    assert a.model_dump() == b.model_dump()
    assert len({c.identity.species for c in a.characters}) == 5
    assert not [n for c in a.characters for n in check_name(c.name)]
    assert check_name("Mickey") and check_words("a Pixar style movie")


def test_owner_story_passes_child_safety_review(mosslight):
    from cartoon_studio.generators.story import write_episode

    e = write_episode(import_legacy(mosslight, "mosslight-valley", {"Fernbridge clearing": 1, "Mossy creek": 1, "Root garden": 1,
                                                                    "Valley panorama": 1}), "seed-glow")
    assert {s.act for s in e.scenes} == {"hook", "introduction", "development", "conflict", "climax", "resolution", "ending"}
    lines = " ".join(s.dialogue["text"] for s in e.scenes)
    for owner_line in ("The last seed isn't glowing!", "Let's listen before we pull.", "Every little light belongs."):
        assert owner_line in lines


def test_probe_fails_on_missing_or_fake_video(tmp_path):
    assert probe_video(str(tmp_path / "nope.mp4"))["status"] in ("FAIL", "BLOCKED")
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not a video")
    assert probe_video(str(fake))["status"] in ("FAIL", "BLOCKED")


def test_step_record_default():
    assert StepRecord().status == "pending"


def test_staging_rule_catches_hidden_speakers_and_crowds():
    from cartoon_studio.generators.story import staging_issues

    beat = {"speaker": "d", "actors": [{"id": x} for x in "abcd"]}
    issues = staging_issues([beat])
    assert any("4 characters" in i for i in issues) and any("d speaks but is not on stage" in i for i in issues)
    assert staging_issues([{"speaker": "narrator", "actors": [{"id": "a"}]}]) == []
