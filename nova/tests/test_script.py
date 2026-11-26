import re

from conftest import EN_SCRIPT, ID_SCRIPT, MIXED_SCRIPT

from nova.director import direct, render_script
from nova.enhance import enhance, meaning_check
from nova.script_judge import judge
from nova.textutil import numbers_to_words


def test_analyze_english_script():
    r = judge(EN_SCRIPT)
    assert r["language"]["primary"] == "en" and not r["language"]["is_mixed"]
    assert 0 <= r["score"] <= 100
    assert set(r["quality"]["parameters"]) == {"grammar", "structure", "repetition", "clarity", "flow",
                                               "engagement", "suitability"}
    assert r["emotion"]["dominant"] in ("commercial", "excitement")
    digits = [d["word"] for d in r["language"]["difficult_words"]]
    assert "15" in digits and "%" in r["language"]["symbols"]
    assert r["voiceover"]["speaking_speed_wpm"] > 0 and r["voiceover"]["pauses"]


def test_analyze_indonesian_script():
    r = judge(ID_SCRIPT)
    assert r["language"]["primary"] == "id" and not r["language"]["is_mixed"]
    assert r["stats"]["sentences"] == 4


def test_analyze_mixed_language_script():
    r = judge(MIXED_SCRIPT)
    assert r["language"]["is_mixed"]
    tags = {s["language"] for s in r["language"]["sentence_languages"]}
    assert "en" in tags and ("id" in tags or "mixed" in tags)


def test_quality_flags_problems_and_scores_lower():
    bad = "um so the the product is is good  . we sell product product product (very cheap) at 50% off"
    good = judge(EN_SCRIPT)["score"]
    r = judge(bad)
    assert r["score"] < good
    issues = " ".join(i for p in r["quality"]["parameters"].values() for i in p["issues"])
    assert "repeated word" in issues and "filler" in issues and "space before punctuation" in issues


def test_unnatural_translation_detected():
    r = judge("Produk ini adalah merupakan solusi yang sangat bagus sekali untuk kamu.")
    assert {u["text"].lower() for u in r["language"]["unnatural_phrases"]} >= {"adalah merupakan", "sangat bagus sekali"}


def test_numbers_to_words():
    assert numbers_to_words("Rp25.000", "id") == "dua puluh lima ribu rupiah"
    assert numbers_to_words("15 years", "en") == "fifteen years"
    assert numbers_to_words("20%", "id") == "dua puluh persen"


def test_enhance_three_modes_preserve_meaning():
    text = "um i do not think this is is the best way. we have 3 options & you can choose one"
    outs = {m: enhance(text, m) for m in ("natural", "professional", "expressive")}
    for m, r in outs.items():
        assert r["meaning"]["preserved"], (m, r["meaning"])
        assert not re.search(r"\bis is\b", r["enhanced"]) and "um" not in r["enhanced"].lower().split()
        assert "We have" in r["enhanced"]
        assert "three" in r["enhanced"] and "&" not in r["enhanced"]
        assert r["enhanced"].endswith((".", "?", "!"))
    assert "don't" in outs["natural"]["enhanced"]
    assert "do not" in outs["professional"]["enhanced"]


def test_compare_original_and_enhanced():
    r = enhance(ID_SCRIPT + " Tapi aku tetap bertahan.", "expressive")
    ops = {d["op"] for d in r["diff"]}
    assert "equal" in ops and ("insert" in ops or "delete" in ops)
    assert any(c["rule"] == "dramatic pause before twist" for c in r["changes"])
    rebuilt = " ".join(d["text"] for d in r["diff"] if d["op"] != "delete")
    assert rebuilt.split() == r["enhanced"].split()


def test_meaning_check_rejects_changed_message():
    check = meaning_check("We deliver fresh bread every morning in Jakarta.",
                          "Our company sells cars and motorcycles worldwide.", "en")
    assert not check["preserved"]


def test_long_sentence_split():
    long = ("We started this company in a small garage with two friends and a lot of hope, and after many "
            "difficult years we finally opened our first real store in the middle of the city.")
    r = enhance(long, "natural")
    assert r["enhanced"].count(".") >= 2


def test_director_sentence_directions():
    dirs = direct("Welcome to our store. Discover something special today!", "expressive")
    assert len(dirs) == 2
    assert dirs[1].emotion == "excitement" and dirs[1].prosody.rate > 1 and dirs[1].prosody.pitch_semitones > 0
    assert "special" in dirs[1].prosody.emphasis
    assert dirs[0].pause_after_ms > 0 and dirs[-1].pause_after_ms == 0
    script = render_script(dirs)
    assert "[Excited tone]" in script and "[Pause:" in script and "[Emphasis: special" in script


def test_director_breath_in_long_sentence():
    d = direct("When we arrived in Islamabad after a very long flight, the whole family was waiting for us "
               "at the airport with flowers.", "natural")[0]
    assert d.breath_after_word and 0 < d.breath_after_word < len(d.text.split())
