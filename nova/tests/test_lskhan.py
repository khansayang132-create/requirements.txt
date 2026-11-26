"""Bridge from the LSKhan Studio autopilot: plan JSON or "Salin naskah" text -> filled -> voiceover."""
import time

import pytest
from fastapi.testclient import TestClient

from nova.api import create_app
from nova.lskhan import PlanError, clean_say, fill, parse, segments

PLAN = {  # same shape as plans/auto-YYYY-MM-DD written by the "LSKhan daily video plan" task
    "source": "autopilot", "lang": "id", "status": "ide",
    "plan": {
        "type": "Budaya", "title": "Sambal vs Chutney: Aku Coba Dua-Duanya",
        "scenes": [
            {"t": "0-2s", "say": "Sambal Indonesia vs chutney Pakistan… mana yang lebih pedas?", "text": "SAMBAL 🇮🇩 vs CHUTNEY 🇵🇰"},
            {"t": "2-6s", "say": "Pertama sambal: [sambal asli buatanmu]. Rasanya → [kesan aslimu].", "text": "SAMBAL: [KATA KUNCI]"},
            {"t": "6-10s", "say": "Terus aku tanya suami: yang mana? → [jawaban asli suami].", "text": "KATA SUAMI"},
            {"t": "10-13s", "say": "Kalau kamu… pilih sambal atau chutney?", "text": "KAMU PILIH YANG MANA? 👇"},
        ],
        "needs": ["Which sambal do you really make?"],
    },
}
ANSWERS = {"s1p0": "sambal terasi resep ibuku", "s1p1": "pedasnya bikin kangen rumah", "s2p0": "dua-duanya enak, katanya sambil tertawa"}


def copy_text(plan):
    """What LSKhan Studio's "Salin naskah" button copies."""
    return "\n".join(f"{s['t']}  {s['say']}" + (f"\n   [TEXT] {s['text']}" if s["text"] else "") for s in plan["plan"]["scenes"])


def test_parse_json_and_copied_text_agree():
    a, b = parse(PLAN), parse(copy_text(PLAN))
    assert [s["say"] for s in a["scenes"]] == [s["say"] for s in b["scenes"]]
    assert a["placeholder_count"] == b["placeholder_count"] == 3
    assert a["scenes"][1]["slot_s"] == 4.0 and a["emotion"] == "happiness"
    assert b["scenes"][0]["text"].startswith("SAMBAL")


def test_placeholders_must_be_answered_never_invented():
    plan = parse(PLAN)
    with pytest.raises(PlanError) as e:
        fill(plan, {"s1p0": "sambal terasi"})
    assert [m["id"] for m in e.value.args[1]] == ["s1p1", "s2p0"]
    with pytest.raises(PlanError):
        fill(plan, ANSWERS | {"s2p0": "[jawaban]"})  # brackets back in are not an answer
    segs = segments(plan, fill(plan, ANSWERS))
    assert all("[" not in s["text"] and "→" not in s["text"] and "🇮🇩" not in s["text"] for s in segs)
    assert segs[0]["emotion"] == "excitement" and segs[1]["emotion"] == "happiness"
    assert "sambal terasi resep ibuku" in segs[1]["text"]


def test_bilingual_lines_voice_the_indonesian_part():
    assert clean_say("Aku salah. (I was wrong.) Ternyata… (It turns out…)", "both") == "Aku salah. Ternyata…"
    assert clean_say("Aku salah (sedikit).", "id") == "Aku salah (sedikit)."


def test_parse_rejects_garbage():
    for bad in ("", "hello there", "{not json"):
        with pytest.raises(PlanError):
            parse(bad)


def test_render_through_api(settings):
    c = TestClient(create_app(settings))
    p = c.post("/api/lskhan/parse", json={"source": copy_text(PLAN)}).json()
    assert p["placeholder_count"] == 3
    r = c.post("/api/lskhan/render", json={"source": copy_text(PLAN), "answers": {"s1p0": "x"}})
    assert r.status_code == 422 and len(r.json()["missing"]) == 2
    r = c.post("/api/lskhan/render", json={"source": PLAN, "answers": ANSWERS, "formats": ["mp3"]}).json()
    for _ in range(600):
        j = c.get(f"/api/jobs/{r['job_id']}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert j["status"] == "done", j["error"]
    res = j["result"]
    assert res["lskhan"]["title"].startswith("Sambal") and len(res["lskhan"]["timing"]) == 4
    assert all(row["speech_s"] > 0 for row in res["lskhan"]["timing"])
    assert {s["scene"] for s in res["sentences"]} == {0, 1, 2, 3}
    assert abs(res["mastering"]["output_lufs"] + 14) < 1.0  # TikTok loudness by default
    assert not any("[" in s["spoken_text"] for s in res["sentences"])
