"""Whole pipeline with the free mock provider, plus the spend gate and resume rules."""

import asyncio
import json
from pathlib import Path

import pytest
from conftest import needs_ffmpeg

from dhfactory.agents import ALL_AGENTS, Context
from dhfactory.agents.production_manager import ProductionManagerAgent
from dhfactory.errors import SpendNotApproved
from dhfactory.pipeline import cost_guard
from dhfactory.providers.base import ClipResult, Provider
from dhfactory.state import ProductionState

SCRIPT = "Hello, I'm Amara Lin, a fictional presenter created for this test. Today I'll show you how a short video is made, from script to screen."


def run(settings, state):
    ctx = Context.for_job(settings, state.job_id)
    return asyncio.run(ProductionManagerAgent(ctx).run(state, "m")), ctx


def test_agents_have_names_and_descriptions(settings):
    ctx = Context.for_job(settings, "x")
    names = set()
    for cls in ALL_AGENTS:
        a = cls(ctx)
        assert a.name and a.description
        names.add(a.name)
    assert len(names) == 7


@needs_ffmpeg
def test_dry_run_produces_checked_mock_video_and_resumes(settings, ws):
    state = ProductionState(job_id="demo", script=SCRIPT)
    res, ctx = run(settings, state)
    rep = res.metadata
    assert rep["final_video"] and Path(rep["final_video"]).is_file()
    qc = json.loads((Path(rep["final_video"]).parent / "qc_report.json").read_text())
    assert qc["checks"]["resolution"]["status"] == "PASS" and qc["checks"]["audio_stream"]["status"] == "PASS"
    assert qc["overall"] == "BLOCKED" and qc["checks"]["real_production"]["status"] == "BLOCKED"   # a mock is never "PASS"
    assert (ws / "characters" / "amara-lin" / "identity.json").is_file()
    assert (ws / "audio" / "demo" / "speech_manifest.json").is_file()
    # resume: nothing runs again
    saved = ProductionState.load(ctx.job_dir / "state.json")
    before = {k: v.finished_at for k, v in saved.steps.items()}
    run(settings, saved)
    after = {k: v.finished_at for k, v in ProductionState.load(ctx.job_dir / "state.json").steps.items()}
    assert before == after


class PaidAvatar(Provider):
    name = "paidfake"
    capabilities = frozenset({"avatar"})
    env_var = None
    calls = 0

    def require_key(self):
        return "x"

    def estimate_usd(self, capability, seconds):
        return 0.5

    def talking_video(self, text, audio, out, size, duration, **kw):
        PaidAvatar.calls += 1
        raise RuntimeError("should not be reached in this test")


def test_paid_step_blocked_without_approval_independent_steps_continue(settings, ws):
    state = ProductionState(job_id="paid", script=SCRIPT, providers={"voice": "mock", "avatar": "paidfake", "image": "mock", "video": "none"})
    ctx = Context.for_job(settings, "paid")
    ctx.provider_overrides["paidfake"] = PaidAvatar(settings)
    ctx.presenter = {"paidfake": {}}
    asyncio.run(ProductionManagerAgent(ctx).run(state, "m"))
    assert state.steps["07_talking_avatar"].status == "blocked_pending_approval"
    assert state.steps["06_voice"].status == "success" and state.steps["04_identity"].status == "success"
    assert state.steps["14_export"].status == "blocked" and PaidAvatar.calls == 0 and state.spent_usd == 0


def test_cost_guard_rules(settings):
    p = PaidAvatar(settings)
    s = ProductionState(job_id="c", script="x")
    with pytest.raises(SpendNotApproved, match="approve-spend"):
        cost_guard.authorize(s, p, "avatar", 10, 5)
    s.spend_approved = True
    assert cost_guard.authorize(s, p, "avatar", 10, 5) == 0.5
    s.spent_usd = 4.8
    with pytest.raises(SpendNotApproved, match="DHF_MAX_SPEND_USD"):
        cost_guard.authorize(s, p, "avatar", 10, 5)
    unknown = PaidAvatar(settings)
    unknown.estimate_usd = lambda c, a: None
    s.spent_usd = 0
    with pytest.raises(SpendNotApproved, match="pricing.json"):
        cost_guard.authorize(s, unknown, "avatar", 10, 5)


class RecordingAvatar(PaidAvatar):
    name = "recfake"
    paid = False

    def talking_video(self, text, audio, out, size, duration, **kw):
        RecordingAvatar.kw = kw
        out.write_bytes(b"")
        return ClipResult(video=out, provider=self.name, provider_job_id="JOB1")


def test_paid_job_id_is_reused_on_resume(settings):
    state = ProductionState(job_id="r", script=SCRIPT, providers={"voice": "mock", "avatar": "recfake", "image": "mock", "video": "none"})
    state.paid_jobs["07_talking_avatar"] = "JOB1"
    ctx = Context.for_job(settings, "r")
    ctx.provider_overrides["recfake"] = RecordingAvatar(settings)
    ctx.presenter = {"recfake": {}}
    from dhfactory.agents import AvatarEngineerAgent

    state.audio_manifest = {"duration": 5}
    asyncio.run(AvatarEngineerAgent(ctx).run(state, "07_talking_avatar"))
    assert RecordingAvatar.kw.get("resume_job_id") == "JOB1"


def test_real_likeness_needs_consent(settings):
    from dhfactory.agents import DigitalHumanDirectorAgent

    ctx = Context.for_job(settings, "l")
    ctx.presenter = {"character": {"name": "Real Person", "fictional": False, "likeness_consent": ""}}
    res = asyncio.run(DigitalHumanDirectorAgent(ctx).run(ProductionState(job_id="l", script="x"), "02"))
    assert res.status == "failed" and "consent" in res.error
