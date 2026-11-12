#!/usr/bin/env python3
"""Simulate N days of story production with the real story engine and its real dedupe rules.

    python tools/simulate_runway.py --days 365            # the yearly check
    python tools/simulate_runway.py --days 60 --quiet     # the CI check

For every day and every slot in ``config/studio.yaml`` it calls ``StoryEngine.generate`` with
the full history so far and the stories already planned for that day, exactly as production
does. A slot whose engine call raises is counted as *skipped* (production skips the slot rather
than repeat itself). Every accepted story is then re-checked here, independently of the engine:
its signature must be new, and its script must not be more similar than the limit to the last
40 scripts, to any earlier script of its own format, or (0.4) to the same day.

It prints the fill rate per slot, the skipped slots, the highest similarity that was accepted,
how often each format was used, and the unique-story runway left in every category at the end.
The exit status is non-zero when any slot fills less than ``--threshold`` of its days, when an
exact repeat got through, or when an accepted script is over the similarity limit.

Nothing is rendered and nothing is written unless ``--json`` is given.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wonderland import config  # noqa: E402
from wonderland.departments import story as story_mod  # noqa: E402
from wonderland.departments.story import StoryEngine, runway  # noqa: E402
from wonderland.departments.story_formats import CATEGORY_NAMES, FORMATS  # noqa: E402

SAME_DAY_LIMIT = 0.4       # the engine's fixed same-day limit (story.py)
RECENT_WINDOW = 40         # the engine compares with this many latest scripts (story.py)


def _memoize_shingles() -> None:
    """Cache ``story.shingles`` (a pure function of the text). Same results, about 10x faster."""
    if not hasattr(story_mod.shingles, "cache_info"):
        story_mod.shingles = functools.lru_cache(maxsize=6000)(story_mod.shingles)


def _reason_kind(reason: str) -> str:
    for key, kind in (("exact repeat", "exact_repeat"), ("too similar", "too_similar"), ("compliance", "compliance"),
                      ("format error", "format_error")):
        if reason.startswith(key):
            return kind
    return "other"


def simulate(days: int, universe: dict | None = None, studio: dict | None = None, *, seed: str = "sim",
             max_similarity: float | None = None, audit_all: bool = False, cache: bool = True, progress=None) -> dict:
    """Run the simulation and return a plain-data report (see ``render_report`` for the printed form)."""
    universe = universe or config.load_universe()
    studio = studio or config.load_studio()
    if cache:
        _memoize_shingles()
    story_cfg = dict(studio.get("story") or {})
    if max_similarity is not None:
        story_cfg["max_similarity"] = max_similarity
    engine = StoryEngine(universe, story_cfg)
    slots = [{"id": s["id"], "kind": s.get("kind", ""), "categories": list(s["categories"])} for s in studio["slots"]]
    sim = story_mod.similarity

    history: list[dict] = []
    used: set[str] = set()
    filled = Counter()
    skipped: list[dict] = []
    usage, per_category = Counter(), Counter()
    rejects: dict[str, Counter] = {}
    thin: list[dict] = []           # slots that found fewer drafts than the engine wanted
    exact_repeats = 0
    max_hist = {"value": 0.0}
    max_day = {"value": 0.0}
    max_global = {"value": 0.0}
    over_limit: list[dict] = []
    t0 = time.time()

    for day in range(1, days + 1):
        same_day: list[dict] = []
        for slot in slots:
            try:
                story, report = engine.generate(slot["categories"], f"{seed}:d{day}:s{slot['id']}", history, same_day)
            except RuntimeError as exc:
                skipped.append({"day": day, "slot": slot["id"], "error": str(exc)[:240]})
                continue
            script = story.script()
            sig = report["signature"]
            if sig in used:
                exact_repeats += 1
            # independent re-check of the engine's similarity rules
            pool = history[-RECENT_WINDOW:] + [h for h in history[:-RECENT_WINDOW] if h["format"] == story.format]
            s_hist, s_with = 0.0, None
            for h in pool:
                v = sim(script, h["script"])
                if v > s_hist:
                    s_hist, s_with = v, h
            s_day = max((sim(script, h["script"]) for h in same_day), default=0.0)
            where = {"day": day, "slot": slot["id"], "format": story.format, "title": story.title}
            if s_hist > max_hist["value"]:
                max_hist = {"value": round(s_hist, 4), **where, "against": s_with["title"] if s_with else None}
            if s_day > max_day["value"]:
                max_day = {"value": round(s_day, 4), **where}
            if s_hist > engine.max_similarity or s_day > SAME_DAY_LIMIT:
                over_limit.append({**where, "history": round(s_hist, 4), "same_day": round(s_day, 4)})
            if audit_all:
                g = max((sim(script, h["script"]) for h in history), default=0.0)
                if g > max_global["value"]:
                    max_global = {"value": round(g, 4), **where}
            row = {"signature": sig, "format": story.format, "script": script, "cast": list(story.cast), "title": story.title,
                   "category": story.category, "day": day, "slot": slot["id"]}
            history.append(row)
            same_day.append(row)
            used.add(sig)
            filled[slot["id"]] += 1
            usage[story.format] += 1
            per_category[story.category] += 1
            if report["candidates_considered"] < engine.candidates:
                thin.append({"day": day, "slot": slot["id"], "drafts": report["candidates_considered"]})
            for r in report["rejected"]:
                rejects.setdefault(r["format"], Counter())[_reason_kind(r["reason"])] += 1
        if progress and (day % 30 == 0 or day == days):
            progress(f"day {day}/{days}: {len(history)} stories, {len(skipped)} skipped, {time.time() - t0:.0f}s")

    categories = sorted(CATEGORY_NAMES)
    left = runway(universe, history, categories, max_similarity=engine.max_similarity)
    slot_rows = []
    for slot in slots:
        n = filled[slot["id"]]
        slot_rows.append({"id": slot["id"], "kind": slot["kind"], "categories": slot["categories"], "filled": n, "days": days,
                          "fill_rate": round(n / days, 4) if days else 1.0,
                          "runway_left": sum(left[c] for c in slot["categories"])})
    return {
        "days": days, "seed": seed, "slots": slot_rows, "stories": len(history), "planned": days * len(slots),
        "skipped": skipped, "exact_repeats": exact_repeats, "max_similarity_limit": engine.max_similarity,
        "max_similarity_history": max_hist, "max_similarity_same_day": max_day,
        "max_similarity_all_history": max_global if audit_all else None, "over_limit": over_limit,
        "format_usage": {fn.__name__: usage[fn.__name__] for cat in categories for fn in FORMATS[cat]},
        "formats_per_category": {cat: len(FORMATS[cat]) for cat in categories},
        "stories_per_category": {cat: per_category[cat] for cat in categories},
        "runway_left": left, "runway_samples_per_format": 40,
        "thin_slots": thin, "rejects": {k: dict(v) for k, v in sorted(rejects.items())},
        "seconds": round(time.time() - t0, 1), "history": history,
    }


def check(report: dict, threshold: float) -> list[str]:
    """The reasons this run fails (empty list = pass)."""
    problems = []
    for s in report["slots"]:
        if s["fill_rate"] < threshold:
            problems.append(f"slot {s['id']} ({'+'.join(s['categories'])}) filled {s['filled']}/{s['days']} "
                            f"= {s['fill_rate']:.1%}, under {threshold:.0%}")
    if report["exact_repeats"]:
        problems.append(f"{report['exact_repeats']} exact repeats were accepted")
    if report["over_limit"]:
        problems.append(f"{len(report['over_limit'])} accepted scripts are over the similarity limit")
    broken = {f: r["format_error"] for f, r in report["rejects"].items() if r.get("format_error")}
    if broken:
        problems.append("formats that raised: " + ", ".join(f"{f} x{n}" for f, n in broken.items()))
    return problems


def render_report(report: dict, threshold: float, verbose: bool = True) -> str:
    out = [f"Story runway simulation: {report['days']} days x {len(report['slots'])} slots "
           f"(seed '{report['seed']}', similarity limit {report['max_similarity_limit']}, {report['seconds']}s)", ""]
    out.append("Fill rate per slot")
    for s in report["slots"]:
        mark = "ok  " if s["fill_rate"] >= threshold else "FAIL"
        out.append(f"  {mark} slot {s['id']} {s['kind']:<10} {'+'.join(s['categories']):<4} {s['filled']:>4}/{s['days']:<4} "
                   f"{s['fill_rate']:>7.1%}   runway left {s['runway_left']}")
    out.append(f"  total {report['stories']}/{report['planned']} slots filled, {len(report['skipped'])} skipped, "
               f"{report['exact_repeats']} exact repeats")
    if report["skipped"]:
        out.append("")
        out.append("Skipped slots (the engine refused to repeat itself)")
        shown = report["skipped"] if verbose else report["skipped"][:12]
        out.extend(f"  day {s['day']:>3} slot {s['slot']}" for s in shown)
        if len(shown) < len(report["skipped"]):
            out.append(f"  ... and {len(report['skipped']) - len(shown)} more")
    mh, md = report["max_similarity_history"], report["max_similarity_same_day"]
    out.append("")
    out.append("Highest similarity that was accepted")
    out.append(f"  against history (last 40 + same format): {mh['value']:.3f}" + (f"  [{mh['format']}, day {mh['day']}]" if mh["value"] else ""))
    out.append(f"  against the same day:                    {md['value']:.3f}" + (f"  [{md['format']}, day {md['day']}]" if md["value"] else ""))
    if report["max_similarity_all_history"] is not None:
        mg = report["max_similarity_all_history"]
        out.append(f"  against every earlier script (audit):    {mg['value']:.3f}" + (f"  [{mg['format']}, day {mg['day']}]" if mg["value"] else ""))
    out.append("")
    out.append("Stories and runway per category (runway = unique stories still available; a lower bound, 40 samples per format)")
    for cat, n in report["stories_per_category"].items():
        out.append(f"  {cat} {CATEGORY_NAMES[cat]:<26} formats {report['formats_per_category'][cat]:>3}   used {n:>4}   "
                   f"runway left {report['runway_left'][cat]:>4}")
    if verbose:
        out.append("")
        out.append("Format usage (times used / drafts rejected as exact repeat, too similar)")
        for cat in report["formats_per_category"]:
            names = [fn.__name__ for fn in FORMATS[cat]]
            out.append(f"  {cat}:")
            for name in sorted(names, key=lambda f: -report["format_usage"][f]):
                r = report["rejects"].get(name, {})
                extra = "".join(f"  {k} {r[k]}" for k in ("compliance", "format_error", "other") if r.get(k))
                out.append(f"    {name:<26} {report['format_usage'][name]:>4}   / {r.get('exact_repeat', 0):>4} {r.get('too_similar', 0):>4}{extra}")
        if report["thin_slots"]:
            out.append("")
            out.append(f"Slots that found fewer than the wanted number of drafts: {len(report['thin_slots'])} "
                       f"(first on day {report['thin_slots'][0]['day']})")
    problems = check(report, threshold)
    out.append("")
    out.append("RESULT: " + ("PASS" if not problems else "FAIL - " + "; ".join(problems)))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--threshold", type=float, default=0.99, help="minimum fill rate every slot must reach (default 0.99)")
    ap.add_argument("--seed", default="sim", help="seed prefix; a different seed is a different simulated year")
    ap.add_argument("--max-similarity", type=float, default=None, help="override story.max_similarity from studio.yaml")
    ap.add_argument("--audit", action="store_true", help="also compare every script with ALL earlier scripts (slower)")
    ap.add_argument("--no-cache", action="store_true", help="do not memoize the engine's shingle function (slow; for cross-checking)")
    ap.add_argument("--json", help="write the full report, including every script, to this file")
    ap.add_argument("--quiet", action="store_true", help="short report without the per-format table")
    a = ap.parse_args()
    progress = None if a.quiet else (lambda msg: print(msg, file=sys.stderr, flush=True))
    report = simulate(a.days, seed=a.seed, max_similarity=a.max_similarity, audit_all=a.audit, cache=not a.no_cache, progress=progress)
    print(render_report(report, a.threshold, verbose=not a.quiet))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 1 if check(report, a.threshold) else 0


if __name__ == "__main__":
    raise SystemExit(main())
