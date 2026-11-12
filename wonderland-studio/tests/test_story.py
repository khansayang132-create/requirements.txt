"""Story engine tests: every format is compliant, uses only things that exist, and the engine
fills the calendar without repeating itself (and refuses rather than repeats when it cannot)."""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from wonderland import config  # noqa: E402
from wonderland.audio.synth import SFX  # noqa: E402
from wonderland.departments import compliance  # noqa: E402
from wonderland.departments import story as story_mod  # noqa: E402
from wonderland.departments.story import StoryEngine, signature, similarity  # noqa: E402
from wonderland.departments.story_formats import CATEGORY_NAMES, FORMATS, MOVING_ACTIONS, keep_moving  # noqa: E402
from wonderland.render.environments import ENVS  # noqa: E402
from wonderland.render.props import COLORS, LETTERS, PROPS, spoken_name  # noqa: E402

UNI = config.load_universe()
CHARS = {c["id"] for c in UNI["characters"]}
ALL_FORMATS = [fn for cat in sorted(FORMATS) for fn in FORMATS[cat]]
SEEDS = 30
LAYOUTS = {"show", "ground", "sky", "fall", "fly"}
OVERLAY_STYLES = {"word", "number", "letter", "title", "end"}
FX = {None, "sparkle", "hearts", "notes", "zzz"}


def _stage_actions() -> set[str]:
    """The acting actions the renderer knows: the branches of Renderer.pose (stage.py is the source of truth)."""
    src = (ROOT / "wonderland" / "render" / "stage.py").read_text(encoding="utf-8")
    body = src[src.index("def pose("):src.index("def frame(")]
    acts = set(re.findall(r'act == "([a-z_]+)"', body))
    for group in re.findall(r"act (?:not )?in \(([^)]*)\)", body):
        acts |= set(re.findall(r'"([a-z_]+)"', group))
    return acts | {"idle"}


ACTIONS = _stage_actions()


def _stories(fn, n=SEEDS):
    return [fn(random.Random(f"test:{fn.__name__}:{i}"), UNI) for i in range(n)]


def test_stage_actions_parsed():
    assert {"hop", "wave", "nod", "sleep", "point"} <= ACTIONS


def test_every_category_has_formats_and_unique_names():
    assert set(FORMATS) == set(CATEGORY_NAMES)
    names = [fn.__name__ for fn in ALL_FORMATS]
    assert len(names) == len(set(names))
    for cat, fns in FORMATS.items():
        assert len(fns) >= 6, f"category {cat} has only {len(fns)} formats"


@pytest.mark.parametrize("fn", ALL_FORMATS, ids=lambda f: f.__name__)
def test_format_is_compliant(fn):
    engine = StoryEngine(UNI, {})
    for st in _stories(fn):
        verdict = engine.review(st)
        assert verdict["ok"], f"{fn.__name__}: {verdict['errors'][:3]}"
        assert st.format == fn.__name__
        assert st.category in CATEGORY_NAMES and fn in FORMATS[st.category]


@pytest.mark.parametrize("fn", ALL_FORMATS, ids=lambda f: f.__name__)
def test_format_uses_only_things_that_exist(fn):
    for st in _stories(fn):
        assert set(st.cast) <= CHARS
        for i, b in enumerate(st.beats, 1):
            where = f"{fn.__name__} line {i}"
            assert b["speaker"] == "narrator" or b["speaker"] in CHARS, where
            assert b["env"] in ENVS, where
            for a in b["actors"]:
                assert a["id"] in CHARS, where
                assert a["action"] in ACTIONS, f"{where}: unknown action {a['action']!r}"
                if a.get("hold"):
                    assert a["hold"]["name"] in PROPS, where
            for it in b["items"]:
                assert it["name"] in PROPS, f"{where}: unknown prop {it['name']!r}"
                assert it["layout"] in LAYOUTS, where
                col = it.get("color")
                assert col is None or col in COLORS or re.fullmatch(r"#[0-9A-Fa-f]{6}", col), f"{where}: color {col!r}"
                assert 1 <= it.get("count", 1) <= 10, where
            if b.get("transfer"):
                assert b["transfer"]["name"] in PROPS and {b["transfer"]["from"], b["transfer"]["to"]} <= CHARS, where
            ov = b.get("overlay")
            if ov:
                assert ov["style"] in OVERLAY_STYLES and ov["text"].strip(), where
            assert b.get("fx") in FX, where
            assert set(b.get("sfx", [])) <= set(SFX), where
        assert st.beats[-1]["overlay"] and st.beats[-1]["overlay"]["style"] == "end"


@pytest.mark.parametrize("fn", ALL_FORMATS, ids=lambda f: f.__name__)
def test_no_line_breaks_the_limits(fn):
    for st in _stories(fn):
        assert 6 <= len(st.beats) <= compliance.MAX_LINES, f"{fn.__name__}: {len(st.beats)} lines"
        for b in st.beats:
            words = re.findall(r"[A-Za-z']+", b["text"])
            assert 0 < len(words) <= compliance.MAX_WORDS_PER_LINE, f"{fn.__name__}: {b['text']!r}"
            assert not compliance.lint_text(b["text"]), f"{fn.__name__}: {b['text']!r}"
            assert "colour" not in b["text"].lower(), "US spelling"
        assert len(st.title) <= 90


# Older formats that are one fixed script (the engine can air each of them once, then the
# similarity rule retires them). Known and accepted; every OTHER format must have real variety.
ONE_EPISODE_SPECIALS = {"rain_song", "wash_song", "bedtime_routine", "calm_breathing", "rain_to_rainbow", "seed_to_flower",
                        "day_and_night", "float_or_sink", "falling_leaves", "bubbles", "what_to_wear"}


@pytest.mark.parametrize("fn", [f for f in ALL_FORMATS if f.__name__ not in ONE_EPISODE_SPECIALS], ids=lambda f: f.__name__)
def test_format_has_real_variety(fn):
    """Thirty drafts of one format must not all be the same script: most pairs stay under the dedupe limit."""
    stories = _stories(fn)
    assert len({signature(s) for s in stories}) >= 5, f"{fn.__name__} has almost no distinct parameter sets"
    scripts = [s.script() for s in stories]
    pairs = [(a, b) for i, a in enumerate(scripts) for b in scripts[i + 1:]]
    close = sum(1 for a, b in pairs if similarity(a, b) > 0.62)
    assert close < len(pairs) * 0.5, f"{fn.__name__}: {close}/{len(pairs)} draft pairs are near-duplicates"


def test_letters_only_name_drawable_things():
    for letter, words in LETTERS.items():
        for w in words:
            assert w in PROPS, w
            assert spoken_name(w)[0].upper() == letter, f"{w} does not start with {letter}"


def test_keep_moving_adds_a_nod_only_when_needed():
    still = {"bobo": "point", "mimi": "idle"}
    assert keep_moving(still, "bobo", None, "forest", []) == {"bobo": "point", "mimi": "nod"}
    assert keep_moving({"bobo": "look_up"}, "narrator", None, "meadow", []) == {"bobo": "nod"}
    assert keep_moving({"bobo": "point"}, "narrator", None, "night", []) == {"bobo": "point"}
    assert keep_moving({"bobo": "point"}, "narrator", "notes", "forest", []) == {"bobo": "point"}
    assert keep_moving({"bobo": "idle"}, "narrator", None, "forest", [{"name": "sun", "layout": "sky"}]) == {"bobo": "idle"}
    assert keep_moving({"bobo": "sad"}, "narrator", None, "forest", []) == {"bobo": "sad"}
    assert keep_moving({"bobo": "hop"}, "bobo", None, "forest", []) == {"bobo": "hop"}
    assert MOVING_ACTIONS <= ACTIONS


def test_simulation_45_days_fills_every_slot_without_repeats():
    import simulate_runway as sim

    report = sim.simulate(45, seed="pytest", audit_all=True)
    assert report["skipped"] == []
    assert all(s["fill_rate"] == 1.0 for s in report["slots"])
    assert report["exact_repeats"] == 0 and report["over_limit"] == []
    assert report["max_similarity_history"]["value"] <= 0.62
    assert report["max_similarity_same_day"]["value"] <= 0.4
    sigs = [h["signature"] for h in report["history"]]
    assert len(sigs) == len(set(sigs)) == 45 * 4
    assert sim.check(report, 0.99) == []


def _single_format_engine(monkeypatch, fn):
    monkeypatch.setattr(story_mod, "FORMATS", {"X": [fn]})
    monkeypatch.setattr(story_mod, "CATEGORY_NAMES", {"X": "Test"})
    return StoryEngine(UNI, {"format_gap": 6, "max_similarity": 0.62, "candidates": 6})


def _row(st):
    return {"signature": signature(st), "format": st.format, "script": st.script(), "cast": st.cast}


def test_engine_raises_instead_of_repeating_exact_stories(monkeypatch):
    fn = FORMATS["H"][0]
    engine = _single_format_engine(monkeypatch, fn)
    seed = "exhausted"
    # history already holds every story the engine could draft for this slot
    history = [_row(fn(random.Random(f"{seed}:{a}"), UNI)) for a in range(engine.candidates * 6)]
    with pytest.raises(RuntimeError, match="no acceptable story"):
        engine.generate(["X"], seed, history)


def test_engine_raises_when_history_exhausts_a_format(monkeypatch):
    from wonderland.departments.story_formats import countdown_rhyme

    engine = _single_format_engine(monkeypatch, countdown_rhyme)
    history, seen = [], set()
    for i in range(3000):          # every distinct countdown this format can write
        st = countdown_rhyme(random.Random(f"fill:{i}"), UNI)
        if signature(st) not in seen:
            seen.add(signature(st))
            history.append(_row(st))
    for seed in ("a", "b", "c"):
        with pytest.raises(RuntimeError):
            engine.generate(["X"], seed, history)


def test_engine_accepts_a_fresh_story_and_reports_it():
    engine = StoryEngine(UNI, {})
    st, rep = engine.generate(["H"], "fresh", [])
    assert rep["signature"] == signature(st) and rep["compliance"]["ok"]
    assert st.category == "H"
