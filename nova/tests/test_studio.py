"""NOVA Studio engines, orchestrator, scheduler and API. The LLM is replaced by a scripted stub
here so results are deterministic; the live model is exercised in the real-world run (STATUS.md)."""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from nova.audio import load_audio, probe, write_wav
from nova.mastering import manage_silence, map_time
from nova.studio import creative, emotion, lab, mix, scriptgen, subtitles
from nova.studio.db import Store
from nova.studio.learning import Learning
from nova.studio.scheduler import Calendar, Scheduler, next_run

STORY = ("Setiap pagi, Sari bangun sebelum matahari terbit. Suaminya sakit, dan anak-anaknya masih kecil. "
         "Kadang dia menangis diam-diam di dapur. Tapi dia tidak pernah menyerah. Dia terus berjuang untuk keluarganya. "
         "Karena dia percaya, besok selalu membawa harapan baru.")


class StubLLM:
    """Answers like a small local model would, by prompt type."""
    def chat_json(self, system, user, max_tokens=1500, temperature=0.4):
        if "label each sentence" in system:
            n = len([l for l in user.splitlines() if l.strip()])
            return {"labels": [{"i": i, "emotion": ["reflective", "sad", "heartbroken", "determined", "determined",
                                                    "hopeful"][i % 6], "intensity": 55 + 5 * i} for i in range(n)]}
        if "develop" in system:
            return {"concepts": [{"title": "Ibu yang Tidak Menyerah", "angle": "a", "audience": "b",
                                  "hook": "Setiap pagi, Sari bangun sebelum matahari terbit.", "message": "c",
                                  "emotional_direction": "d", "duration_s": 60, "platform": "TikTok"}]}
        return {"purpose": "menginspirasi", "audience": "keluarga", "structure": "hook", "perspective": "third",
                "direction": "hangat", "emotional_journey": ["sad", "determined", "hopeful"],
                "desired_reaction": "terharu", "content_type": "emotional", "factual": False}

    def chat(self, system, user, max_tokens=1200, temperature=0.5):
        return STORY


def test_emotion_engine_directs_every_sentence():
    r = emotion.analyze(STORY)
    s = r["sentences"]
    assert len(s) == 6 and r["arc"]["ending"] == "hopeful"
    assert {d["emotion"] for d in s} >= {"determined", "hopeful"}
    for d in s:
        for k in ("emotion", "intensity", "vocal_energy", "speed", "pitch_direction", "delivery", "pause_before_ms",
                  "pause_after_ms", "emphasis", "breathing", "transition_from_previous", "transition_to_next"):
            assert k in d
        assert d["emotion"] in emotion.LIBRARY and 10 <= d["intensity"] <= 100
    assert all(abs(a["intensity"] - b["intensity"]) <= 30 for a, b in zip(s, s[1:]))  # no wild swings
    assert s[-1]["pause_after_ms"] == 0
    heart = emotion._plan(0, "x", "heartbroken", 85, "t", 1.0)
    assert heart.prosody["volume_db"] < 0 and heart.prosody["rate"] < 1  # intensity is not loudness


def test_emotion_edit_changes_one_sentence_only():
    s = emotion.analyze(STORY)["sentences"]
    new = emotion.edit(s, 2, "vulnerable", 70)
    assert new[2]["emotion"] == "vulnerable" and new[2]["source"] == "user"
    assert [d["emotion"] for i, d in enumerate(new) if i != 2] == [d["emotion"] for i, d in enumerate(s) if i != 2]
    assert "vulnerable" in new[3]["transition_from_previous"]
    with pytest.raises(ValueError):
        emotion.edit(s, 0, "bored")


def test_emotion_llm_labels_are_validated():
    r = emotion.analyze(STORY, llm=StubLLM())
    assert [d["source"] for d in r["sentences"]] == ["llm"] * 6
    assert "[EMOTION: HEARTBROKEN]" in emotion.to_script(r["sentences"])


def test_creative_and_script_engines():
    intent = creative.analyze_intent("Wanita yang terus berjuang untuk keluarganya", StubLLM())
    assert intent["language"] == "id" and intent["content_type"] == "emotional" and intent["source"] == "llm"
    cs = creative.concepts(intent, StubLLM(), n=1)
    assert cs[0]["platform"] == "tiktok" and cs[0]["hook"]
    with pytest.raises(RuntimeError):
        creative.concepts(intent, None)
    g = scriptgen.generate(intent, cs[0], 30, StubLLM())
    from nova.textutil import words
    assert g["words"] == len(words(STORY)) and g["attempts"]
    assert scriptgen.estimate_seconds(STORY, "id") > scriptgen.estimate_seconds(STORY, "en")


def test_lab_analysis_versions_and_compare():
    a = lab.analyze(STORY + " " + STORY)
    assert a["repetition"] and a["estimated_s"] > 0 and "score" in a
    c = lab.compare(STORY, STORY.replace("harapan", "kesempatan"))
    assert c["changes"] == [{"op": "replace", "before": "harapan", "after": "kesempatan"}]
    with pytest.raises(RuntimeError):
        lab.enhance(STORY, "cinematic", operation="expand")  # needs the LLM; never pretends


def test_time_map_moves_timings_onto_mastered_audio():
    sr = 1000
    x = np.zeros(10000)
    x[2000:3000] = 0.5          # speech 2.0-3.0 s
    x[6000:7000] = 0.5          # speech 6.0-7.0 s after a 3 s gap (longer than 1.6 s)
    y, spans = manage_silence(x, sr, return_map=True)
    tm = [[a / sr, b / sr, d / sr] for a, b, d in spans]
    assert abs(map_time(2.0, tm) - 0.15) < 0.02           # leading silence trimmed to 0.15 s
    assert abs(map_time(6.0, tm) - (0.15 + 1.0 + 1.6)) < 0.03  # gap shortened to 1.6 s
    assert y.size / sr == pytest.approx(map_time(7.15, tm), abs=0.02)


def test_subtitles_formats_and_validation(tmp_path):
    tl = [{"index": 0, "scene": 0, "text": "Kalimat pertama yang cukup panjang untuk dipecah menjadi dua baris teks.",
           "start_s": 0.1, "end_s": 3.0}, {"index": 1, "scene": 1, "text": "Kedua.", "start_s": 3.5, "end_s": 4.2}]
    cues = subtitles.cues(tl)
    assert all(len(line) <= 42 for c in cues for line in c["text"].split("\n"))
    paths = subtitles.write_all(cues, tmp_path)
    assert paths["srt"].read_text().startswith("1\n00:00:00,100 --> ")
    assert paths["vtt"].read_text().startswith("WEBVTT")
    assert json.loads(paths["json"].read_text())[-1]["end_s"] == 4.2
    assert subtitles.validate(cues, 4.3) == [] and subtitles.validate(cues, 4.0)


def test_music_ducks_under_voice(tmp_path):
    sr = 16000
    t = np.arange(sr * 4) / sr
    voice = np.where((t > 1) & (t < 3), 0.3 * np.sin(2 * np.pi * 220 * t), 0.0)
    music = write_wav(tmp_path / "m.wav", 0.5 * np.sin(2 * np.pi * 440 * t), sr)
    out, rep = mix.mix(voice, sr, str(music), music_db=-18, duck_db=-12, fade_s=0.1)
    music_part = out - voice
    quiet = np.sqrt(np.mean(music_part[int(0.5 * sr):int(0.9 * sr)] ** 2))
    under = np.sqrt(np.mean(music_part[int(2.0 * sr):int(2.5 * sr)] ** 2))
    assert 10 < 20 * np.log10(quiet / under) < 13 and rep["music"]["duck_db"] == -12  # about the 12 dB asked


def test_scheduler_persists_and_never_runs_twice(tmp_path):
    db = Store(tmp_path / "s.db")
    calls = []

    def fake_run(payload, run_id, key):
        calls.append(key)
        return {"id": None, "status": "completed", "qa_passed": True}

    s = Scheduler(db, fake_run)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
    job = s.create("test", {"idea": "x"}, {"type": "once", "at": past}, "UTC", idempotency_key="k1")
    assert s.create("test", {"idea": "x"}, {"type": "once", "at": past}, "UTC", idempotency_key="k1")["duplicate"]
    s2 = Scheduler(Store(tmp_path / "s.db"), fake_run)  # "restart": a new process opens the same database
    assert [j["id"] for j in s2.list()] == [job["id"]]
    claimed_a = s.claim_due()
    claimed_b = s2.claim_due()  # a second worker sees the lease and gets nothing
    assert len(claimed_a) == 1 and claimed_b == []
    r = s.execute(claimed_a[0])
    assert r["status"] == "succeeded" and len(calls) == 1
    assert s2.tick() == [] and s.get(job["id"])["next_run_utc"] is None
    assert db.one("SELECT status FROM job_runs")["status"] == "succeeded"


def test_scheduler_failure_retries_and_notifies(tmp_path):
    db = Store(tmp_path / "s.db")
    s = Scheduler(db, lambda p, r, k: {"id": None, "status": "failed_qa", "qa_passed": False})
    job = s.create("daily", {"idea": "x"}, {"type": "daily", "time": "07:21"}, "Asia/Karachi", max_retries=1)
    db.execute("UPDATE scheduled_jobs SET next_run_utc=? WHERE id=?",
               ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), job["id"]))
    res = s.tick()[0]
    assert res["status"] == "failed" and len(res["attempts"]) == 2
    assert db.one("SELECT COUNT(*) n FROM notifications WHERE level='error'")["n"] == 1
    after = s.get(job["id"])
    assert after["next_run_local"].endswith("+05:00") and "T07:21" in after["next_run_local"]


def test_scheduler_dependency_waits(tmp_path):
    db = Store(tmp_path / "s.db")
    s = Scheduler(db, lambda p, r, k: {"id": None, "status": "completed", "qa_passed": True})
    a = s.create("a", {}, {"type": "daily", "time": "06:00"}, "UTC")
    b = s.create("b", {}, {"type": "daily", "time": "06:00"}, "UTC", depends_on=a["id"])
    db.execute("UPDATE scheduled_jobs SET next_run_utc=? WHERE id=?",
               ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(), b["id"]))
    assert s.claim_due() == []  # a has not succeeded yet


def test_calendar_and_learning(tmp_path):
    db = Store(tmp_path / "s.db")
    cal = Calendar(db)
    rows = cal.recurring("Budaya", "Budaya #{n}", "2026-12-01", 2, [0, 3], "Asia/Jakarta", "19:00", "tiktok")
    assert len(rows) == 4 and cal.update(rows[0]["id"], status="scripted")["status"] == "scripted"
    with pytest.raises(ValueError):
        cal.update(rows[0]["id"], status="viral")
    rep = Learning(db).report()
    assert rep["samples"]["ratings"] == 0 and "Not enough data" in rep["suggestions"][0]


@pytest.fixture
def studio_client(settings, monkeypatch):
    monkeypatch.setenv("NOVA_SCHEDULER", "0")
    from nova.api import create_app
    app = create_app(settings)
    app.state.studio.orch.llm = lambda: StubLLM()
    with TestClient(app) as c:
        yield c, app.state.studio


def _wait(c, pid, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        p = c.get(f"/api/v100/productions/{pid}").json()
        if p["status"] in ("completed", "failed", "failed_qa"):
            return p
        time.sleep(0.5)
    raise AssertionError("production timed out")


def test_end_to_end_production_api(studio_client):
    c, studio = studio_client
    p = c.post("/api/v100/productions", json={"idea": "Wanita yang terus berjuang untuk keluarganya",
                                               "duration_s": 30, "engine": "espeak-ng"}).json()
    done = _wait(c, p["id"])
    assert done["status"] == "completed", done.get("error")
    assert [s["status"] for s in done["stages"]] == ["done"] * 11
    assert done["qa_passed"] and {a["format"] for a in done["assets"]} == {"wav", "mp3"}
    wav = c.get(f"/api/v100/productions/{p['id']}/files/production.wav")
    assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
    srt = c.get(f"/api/v100/productions/{p['id']}/files/subtitles.srt").text
    assert srt.count("-->") >= 6
    tl = c.get(f"/api/v100/emotion/{done['script_version_id']}").json()
    assert len(tl) == 6
    # edit one emotion, redo audio onwards, the earlier stages are not regenerated
    script_done = next(s for s in done["stages"] if s["stage"] == "script")["finished_at"]
    assert c.put(f"/api/v100/emotion/{done['script_version_id']}/2", json={"emotion": "vulnerable"}).status_code == 200
    c.post(f"/api/v100/productions/{p['id']}/redo/audio")
    again = _wait(c, p["id"])
    assert again["status"] == "completed"
    assert next(s for s in again["stages"] if s["stage"] == "script")["finished_at"] == script_done
    seg = studio.db.one("SELECT emotion FROM audio_segments WHERE production_id=? AND idx=2", (p["id"],))
    assert seg["emotion"] == "vulnerable"
    assert c.post(f"/api/v100/productions/{p['id']}/feedback", json={"rating": 5}).status_code == 200
    assert c.get("/api/v100/learning").json()["samples"]["ratings"] == 1


def test_failed_production_resumes_from_checkpoint(studio_client):
    c, studio = studio_client
    orig = studio.orch._stage_audio
    studio.orch._stage_audio = lambda *a: (_ for _ in ()).throw(RuntimeError("engine crashed"))
    p = c.post("/api/v100/productions", json={"script": STORY, "engine": "espeak-ng"}).json()
    failed = _wait(c, p["id"])
    assert failed["status"] == "failed" and "audio" in failed["error"]
    emotion_done = next(s for s in failed["stages"] if s["stage"] == "emotion")["finished_at"]
    studio.orch._stage_audio = orig
    c.post(f"/api/v100/productions/{p['id']}/resume")
    ok = _wait(c, p["id"])
    assert ok["status"] == "completed"
    assert next(s for s in ok["stages"] if s["stage"] == "emotion")["finished_at"] == emotion_done


def test_api_validation_and_scheduler_endpoints(studio_client):
    c, studio = studio_client
    assert c.post("/api/v100/productions", json={}).status_code == 422
    assert c.post("/api/v100/schedule/jobs", json={"name": "x", "production": {"idea": "y"},
                                                   "schedule": {"type": "hourly"}}).status_code == 422
    j = c.post("/api/v100/schedule/jobs", json={"name": "Daily", "production": {"idea": "y"}, "timezone": "Asia/Karachi",
                                                "schedule": {"type": "daily", "time": "07:21"}}).json()
    assert j["next_run_local"].endswith("+05:00")
    assert c.get("/api/v100/schedule/jobs").json()[0]["id"] == j["id"]
    assert c.get("/api/v100/productions/x/files/../../secret.key").status_code == 404
    lib = c.get("/api/v100/emotion/library").json()
    assert len(lib) == 26
    assert any(a["name"] == "espeak-ng" and a["status"] == "available" for a in c.get("/api/v100/voice/adapters").json())
