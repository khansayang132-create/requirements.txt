"""Improvement department: learn from real results, one variable at a time.

* **Format weights.** Each story format's average view percentage is compared with the channel
  average; formats that hold attention get a small preference (0.8-1.2×) in story selection.
  Needs at least ``MIN_VIDEOS`` measured videos per format; until then the weight stays 1.0.
* **Controlled experiments.** Exactly one experiment runs at a time and changes exactly one
  variable (a metadata setting). Episodes are assigned to a variant by a stable hash of their id.
  A winner is declared only with ``MIN_PER_VARIANT`` measured videos per variant and a difference
  larger than ``MIN_EFFECT``; otherwise the result is "inconclusive" and the default stays.

Nothing here runs on guesses: with no analytics rows the department reports "no data" and
changes nothing.
"""

from __future__ import annotations

import hashlib
import json
import statistics

from ..protocol import AgentReport
from .analytics import per_video

MIN_VIDEOS = 3
MIN_PER_VARIANT = 8
MIN_EFFECT = 0.15
MIN_DAYS = 5
EXPERIMENT_QUEUE = [
    {"name": "title-branding-1", "variable": "title_style", "hypothesis": "Adding the channel name to the title changes views per video",
     "metric": "views", "variants": {"A": {"title_style": "plain"}, "B": {"title_style": "branded"}}},
    {"name": "description-lead-1", "variable": "description_lead", "hypothesis": "Leading with the learning goal changes average view percentage",
     "metric": "averageViewPercentage", "variants": {"A": {"description_lead": "summary"}, "B": {"description_lead": "learning_goal"}}},
]


def running(db) -> dict | None:
    row = db.one("SELECT * FROM experiments WHERE status='running' ORDER BY id LIMIT 1")
    if row:
        row["variants"] = json.loads(row["variants"])
    return row


def ensure_experiment(studio) -> dict | None:
    exp = running(studio.db)
    if exp:
        return exp
    done = {r["name"] for r in studio.db.q("SELECT name FROM experiments")}
    for e in EXPERIMENT_QUEUE:
        if e["name"] not in done:
            studio.db.conn.execute("INSERT INTO experiments(name,variable,variants,hypothesis,metric,started_at) VALUES(?,?,?,?,?,?)",
                                   (e["name"], e["variable"], json.dumps(e["variants"]), e["hypothesis"], e["metric"],
                                    studio.now().strftime("%Y-%m-%dT%H:%M:%SZ")))
            return running(studio.db)
    return None


def assignment(studio, ep: dict) -> dict:
    """The experiment variant for an episode ({} when no experiment runs). Stable across retries."""
    if not studio.cfg.get("improvement", {}).get("experiments", True):
        return {}
    exp = ensure_experiment(studio)
    if not exp:
        return {}
    keys = sorted(exp["variants"])
    pick = keys[int(hashlib.sha1(f"{exp['name']}:{ep['id']}".encode()).hexdigest(), 16) % len(keys)]
    return {"name": exp["name"], "variable": exp["variable"], "variant": pick, "settings": exp["variants"][pick]}


def evaluate(studio, exp: dict) -> dict:
    eps = studio.db.q("SELECT id, video_id, metadata FROM episodes WHERE status='published' AND video_id IS NOT NULL")
    groups: dict[str, list[float]] = {k: [] for k in exp["variants"]}
    for e in eps:
        meta = json.loads(e["metadata"] or "{}")
        tag = meta.get("experiment") or {}
        if tag.get("name") != exp["name"]:
            continue
        pv = per_video(studio.db, e["video_id"])
        if pv.get("days_with_data", 0) >= MIN_DAYS and exp["metric"] in pv:
            groups[tag["variant"]].append(float(pv[exp["metric"]]))
    counts = {k: len(v) for k, v in groups.items()}
    if min(counts.values()) < MIN_PER_VARIANT:
        return {"decided": False, "counts": counts, "reason": f"need {MIN_PER_VARIANT} measured videos per variant"}
    means = {k: statistics.mean(v) for k, v in groups.items()}
    base = means["A"] or 1e-9
    effect = (means["B"] - means["A"]) / base
    if abs(effect) < MIN_EFFECT:
        return {"decided": True, "result": "inconclusive", "winner": "A", "means": means, "effect": round(effect, 3), "counts": counts}
    return {"decided": True, "result": "significant difference", "winner": "B" if effect > 0 else "A", "means": means,
            "effect": round(effect, 3), "counts": counts}


def format_weights(studio) -> dict:
    rows = studio.db.q("SELECT format, video_id FROM episodes WHERE status='published' AND video_id IS NOT NULL AND format IS NOT NULL")
    by_fmt: dict[str, list[float]] = {}
    for r in rows:
        pv = per_video(studio.db, r["video_id"])
        if pv.get("days_with_data", 0) >= MIN_DAYS and "averageViewPercentage" in pv:
            by_fmt.setdefault(r["format"], []).append(pv["averageViewPercentage"])
    allv = [x for v in by_fmt.values() for x in v]
    if len(allv) < MIN_VIDEOS * 2:
        return {}
    channel = statistics.mean(allv)
    return {f: round(max(0.8, min(1.2, statistics.mean(v) / channel)), 3) for f, v in by_fmt.items() if len(v) >= MIN_VIDEOS}


def handle_improve(studio, task: dict, ep: dict | None) -> AgentReport:
    measured = studio.db.scalar("SELECT COUNT(DISTINCT video_id) FROM analytics") or 0
    if not measured:
        return AgentReport("improvement", task["key"], "skipped", errors=["no analytics data yet"], next_action="nothing changes until real data exists")
    weights = format_weights(studio)
    if weights:
        studio.db.set("story_weights", weights, studio.now())
    exp = running(studio.db)
    verdict = evaluate(studio, exp) if exp else None
    if exp and verdict and verdict["decided"]:
        studio.db.conn.execute("UPDATE experiments SET status='done', ended_at=?, result=?, decision=? WHERE id=?",
                               (studio.now().strftime("%Y-%m-%dT%H:%M:%SZ"), json.dumps(verdict), f"keep variant {verdict['winner']}", exp["id"]))
        if verdict["winner"] == "B":
            prefs = studio.db.get("metadata_defaults", {}) or {}
            prefs.update(exp["variants"]["B"])
            studio.db.set("metadata_defaults", prefs, studio.now())
    return AgentReport("improvement", task["key"], "success",
                       output={"videos_measured": measured, "format_weights": weights, "experiment": exp["name"] if exp else None, "verdict": verdict},
                       evidence=[{"basis": "youtube analytics rows in the database"}], next_action="report")
