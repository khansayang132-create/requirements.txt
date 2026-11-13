import json
from pathlib import Path

import pytest

from auravox import production, router, voices
from auravox.queue import Blocked, Queue

CAST = [{"id": "C-KID", "name": "Kid", "age": 9, "voice": {"espeak_voice": "en-us+f4", "pitch": 82}},
        {"id": "C-DAD", "name": "Dad", "age": 40, "voice": {"espeak_voice": "en-us+m3", "pitch": 40}},
        {"id": "C-GRAN", "name": "Gran", "age": 75, "voice": {"espeak_voice": "en-us+f2", "pitch": 35}}]


@pytest.fixture
def cast(studio):
    vids = [voices.create(studio, voices.from_character(c)) for c in CAST]
    for v in vids:
        voices.audition(studio, v, 2)
    return voices.select_cast(studio, vids, "test director")


def test_router_never_substitutes_language(studio):
    r = router.route(studio, {"language": "tlh"})
    assert r["selected"] is None and any("no 'tlh'" in x["reason"] for x in r["rejected"])
    r = router.route(studio, {"language": "id", "emotion": "sad", "need_timing": True})
    assert r["selected"] == "espeak-ng" and any("piper" == x["engine"] for x in r["rejected"])


def test_cast_is_distinct_and_locked(studio, cast):
    assert cast["distinct"] and cast["min_pitch_separation"] >= 0.15
    with pytest.raises(voices.VoiceLocked):
        voices.create(studio, voices.from_character(CAST[0]))            # approved identity cannot be redesigned silently
    v = studio.db.one("SELECT * FROM voices WHERE voice_id='AVX-VOICE-C-KID'")
    prof = dict(v["profile"], pitch=10)
    studio.db.update("voices", "voice_id", v["voice_id"], profile=prof)   # tampering with the stored profile
    with pytest.raises(voices.VoiceLocked, match="hash mismatch"):
        voices.approved(studio, "C-KID")


def test_screenplay_to_dialogue_with_takes_metadata_and_lipsync(studio, cast, tmp_path):
    sp = tmp_path / "s.txt"
    sp.write_text("# SCENE S1\nC-KID (excited): We found it!\nC-DAD (calm): Good. Now let's go home.\nC-GRAN (happy): Tea first, please.\n")
    jobs = production.plan_production(studio, sp, "t1")
    Queue(studio).run(production.HANDLERS, workers=2)
    assert Queue(studio).summary() == {"succeeded": 1 + 3 + 1 + 2}
    meta = json.loads((studio.home / "productions" / "t1" / "dialogue.json").read_text())
    assert [r["character_id"] for r in meta["lines"]] == ["C-KID", "C-DAD", "C-GRAN"]
    assert all(r["phonemes"] and r["alignment"] == "engine" and r["end_s"] > r["start_s"] for r in meta["lines"])
    takes = studio.db.q("SELECT * FROM takes WHERE line_id='L01'")
    assert len([t for t in takes if t["kind"] == "raw"]) >= 3 and sum(t["selected"] for t in takes) == 1   # alternatives kept, one selected
    assert json.loads((studio.home / "productions" / "t1" / "lipsync_report.json").read_text())["status"] == "PASS"
    rep = json.loads((studio.home / "productions" / "t1" / "master_report.json").read_text())
    assert abs(rep["loudness"]["after_lufs"] + 16) < 1.0 and Path(rep["master_wav"]).exists()


def test_speaker_substitution_is_blocked(studio, cast, tmp_path):
    sp = tmp_path / "s.txt"
    sp.write_text("C-KID (happy): Hello there!\nC-DAD (happy): Hello yourself.\n")
    jobs = production.plan_production(studio, sp, "t2", master=False)
    q = Queue(studio)
    q.run({k: v for k, v in production.HANDLERS.items() if k != "dialogue.assemble"} | {"dialogue.assemble": lambda s, j: (_ for _ in ()).throw(RuntimeError("hold"))}, workers=1)
    line_job = q.get(jobs["lines"][1])
    res = dict(line_job["result"], voice_id="AVX-VOICE-C-KID")             # pretend the dad line was voiced by the kid
    studio.db.update("jobs", "id", line_job["id"], result=res)
    with pytest.raises(Blocked, match="!= approved"):
        production.h_assemble(studio, q.get(jobs["assemble"]))


def test_line_without_approved_voice_is_blocked(studio):
    with pytest.raises(voices.VoiceLocked):
        production.produce_line(studio, {"id": "J"}, {"line_id": "L1", "character_id": "NOBODY", "text": "hi"})
