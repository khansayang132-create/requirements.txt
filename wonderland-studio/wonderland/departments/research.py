"""Research department: a searchable database of what the studio knows, and where it came from.

Each finding has topic, source, date, findings, confidence and a recommended action. Two kinds
of entries exist and are never mixed up:

* **sourced** — read from a named public page (YouTube's own policy and help pages). Confidence
  "high" means the page says it directly.
* **editorial** — the studio's own judgement (child-development practice, seasonal calendar).
  Marked ``source = "editorial judgement"`` and never above "medium" confidence.

No search volume, view counts or competitor analytics are invented: the studio has no measured
demand data, so opportunity scores below are editorial and say so. Once the channel has real
analytics, the improvement department replaces these priors with measured results.

The daily run refreshes seasonal opportunities and writes ``research_brief`` (formats to favour
this week) that the story department reads.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from ..protocol import AgentReport
from .story_formats import FORMATS

SEED: list[dict] = [
    {"topic": "Made for kids audience setting", "source": "YouTube Help: Determining if your content is made for kids",
     "source_url": "https://support.google.com/youtube/answer/9528076", "date": "2026-11-09", "confidence": "high",
     "findings": "Creators must set the audience; content whose primary audience is children is 'made for kids'. Comments, personalized ads, "
                 "notifications bell and some features are off for such videos.",
     "recommended_action": "Always upload with selfDeclaredMadeForKids=true; never design for comments or 'like and subscribe'.", "tags": ["policy", "audience"]},
    {"topic": "Quality principles for kids and family content", "source": "YouTube Help: Quality principles for kids & family content",
     "source_url": "https://support.google.com/youtube/answer/10774223", "date": "2026-11-09", "confidence": "high",
     "findings": "Low-quality signals include heavily commercial content, encouraging negative behaviour, deceptively educational content, "
                 "content that hinders comprehension, sensational or misleading content, and strange use of children's characters.",
     "recommended_action": "Keep one true idea per video, honest titles, no brands, calm pacing; compliance lint enforces these.", "tags": ["policy", "quality"]},
    {"topic": "Inauthentic (mass-produced, repetitive) content", "source": "YouTube Partner Program policy update, effective 15 July 2025",
     "source_url": "https://support.google.com/youtube/answer/1311392", "date": "2026-11-09", "confidence": "high",
     "findings": "Mass-produced or repetitive content (templated videos with little variation) is not eligible for monetization; channels "
                 "can be removed from the Partner Program.",
     "recommended_action": "Never publish near-duplicates (dedupe ≤ 0.62 similarity, format gap 6), skip a slot rather than repeat, keep "
                           "growing the number of distinct formats, start in review mode.", "tags": ["policy", "monetization", "risk"]},
    {"topic": "Altered or synthetic content disclosure", "source": "YouTube Help: Disclosing use of altered or synthetic content",
     "source_url": "https://support.google.com/youtube/answer/14328491", "date": "2026-11-09", "confidence": "high",
     "findings": "Disclosure is required for realistic altered/synthetic content; clearly unrealistic content such as animation is exempt.",
     "recommended_action": "Leave containsSyntheticMedia unset by default and record the reason; owner may force it in studio.yaml.", "tags": ["policy", "disclosure"]},
    {"topic": "API quota for uploads", "source": "YouTube Data API v3: Quota calculator / determine_quota_cost",
     "source_url": "https://developers.google.com/youtube/v3/determine_quota_cost", "date": "2026-11-09", "confidence": "high",
     "findings": "videos.insert has its own daily allowance; other calls draw from 10,000 units/day (videos.update 50, playlistItems.insert 50, "
                 "videos.list 1).", "recommended_action": "Four uploads/day plus playlist and verification calls fit comfortably; the toolkit's "
                 "quota ledger refuses work that would exceed it.", "tags": ["api", "quota"]},
    {"topic": "Analytics metrics that exist", "source": "YouTube Analytics API: metrics reference",
     "source_url": "https://developers.google.com/youtube/analytics/metrics", "date": "2026-11-09", "confidence": "high",
     "findings": "views, estimatedMinutesWatched, averageViewDuration, averageViewPercentage, subscribersGained are available; Studio's "
                 "impressions/CTR and 'returning viewers' are not in the API.",
     "recommended_action": "Report only API metrics; label impressions/CTR/returning viewers as unavailable.", "tags": ["api", "analytics"]},
    {"topic": "Pacing for ages 2-5", "source": "editorial judgement", "source_url": None, "date": "2026-11-09", "confidence": "medium",
     "findings": "Calm, character-led stories with repetition of one idea and slow, clear speech are easier for preschoolers to follow than "
                 "fast-cut, high-stimulation edits.", "recommended_action": "Keep shot lengths ≥ 1.5 s, two sound effects per shot at most, "
                 "speech at a relaxed rate.", "tags": ["audience", "pacing"]},
]

# Editorial seasonal calendar (month → formats that fit). Northern-hemisphere seasons; the owner
# can edit this list. These are opportunities, not measured demand.
SEASONAL = {
    1: ["day_and_night", "what_to_wear", "counting_stars"], 2: ["helping", "cheering_up", "friends_song"],
    3: ["seed_to_flower", "rain_to_rainbow", "rain_song"], 4: ["seed_to_flower", "rain_to_rainbow", "meadow_explorers"],
    5: ["meadow_explorers", "who_lives_here", "bubbles"], 6: ["float_or_sink", "bubbles", "healthy_snack"],
    7: ["float_or_sink", "wash_hands", "action_song"], 8: ["meadow_explorers", "bubbles", "healthy_snack"],
    9: ["good_morning", "letter_day", "tidy_up"], 10: ["falling_leaves", "what_to_wear", "color_walk"],
    11: ["falling_leaves", "helping", "magic_words"], 12: ["counting_stars", "goodnight_meadow", "sharing"],
}
CRITERIA = ("audience_relevance", "originality", "educational_value", "storytelling_potential", "production_feasibility", "brand_consistency")


def _fp(d: dict) -> str:
    return hashlib.sha1(json.dumps([d["topic"], d["source"], d.get("source_url"), d["date"]], sort_keys=True).encode()).hexdigest()[:20]


def add_finding(db, d: dict, now, kind: str = "finding", scores: dict | None = None) -> bool:
    if d["source"] == "editorial judgement" and d["confidence"] == "high":
        raise ValueError("editorial judgements cannot be high confidence")
    cur = db.conn.execute("INSERT OR IGNORE INTO research(kind,topic,source,source_url,date,findings,confidence,recommended_action,tags,scores,fingerprint,created_at) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (kind, d["topic"], d["source"], d.get("source_url"), d["date"], d["findings"], d["confidence"], d["recommended_action"],
                           json.dumps(d.get("tags", [])), json.dumps(scores) if scores else None, _fp(d), now.strftime("%Y-%m-%dT%H:%M:%SZ")))
    return cur.rowcount == 1


def search(db, text: str = "", tag: str | None = None, limit: int = 50) -> list[dict]:
    like = f"%{text.lower()}%"
    sql = "SELECT * FROM research WHERE (lower(topic) LIKE ? OR lower(findings) LIKE ? OR lower(recommended_action) LIKE ?)"
    args: list = [like, like, like]
    if tag:
        sql += " AND tags LIKE ?"
        args.append(f'%"{tag}"%')
    rows = db.q(sql + " ORDER BY date DESC, id DESC LIMIT ?", (*args, limit))
    for r in rows:
        r["tags"] = json.loads(r["tags"] or "[]")
        r["scores"] = json.loads(r["scores"]) if r["scores"] else None
    return rows


def score_opportunity(fmt: str, category: str, in_season: bool, used_recently: int, measured: float | None) -> dict:
    """0-1 editorial scores per criterion. ``measured`` (relative performance) replaces the relevance prior when it exists."""
    rel = measured if measured is not None else (0.85 if in_season else 0.7)
    scores = {
        "audience_relevance": round(min(1.0, rel), 3),
        "originality": round(max(0.2, 1.0 - 0.15 * used_recently), 3),
        "educational_value": {"A": 0.95, "G": 0.95, "H": 0.9, "D": 0.85, "C": 0.8, "B": 0.7, "E": 0.7, "F": 0.55}.get(category, 0.6),
        "storytelling_potential": 0.75 if category in ("B", "C", "H") else 0.65,
        "production_feasibility": 1.0,
        "brand_consistency": 1.0,
    }
    scores["total"] = round(sum(scores[c] for c in CRITERIA) / len(CRITERIA), 3)
    scores["basis"] = "measured channel performance" if measured is not None else "editorial priors; no search-volume data"
    return scores


def handle_research(studio, task: dict, ep: dict | None) -> AgentReport:
    now = studio.now()
    added = sum(add_finding(studio.db, d, now) for d in SEED)
    today: date = studio.local_day(now)
    season = SEASONAL.get(today.month, [])
    weights = studio.db.get("story_weights", {}) or {}
    recent = studio.db.q("SELECT format, COUNT(*) AS n FROM episodes WHERE format IS NOT NULL AND day >= date(?, '-14 day') GROUP BY format",
                         (f"{today:%Y-%m-%d}",))
    used = {r["format"]: r["n"] for r in recent}
    ranked = []
    for cat, fns in FORMATS.items():
        for fn in fns:
            name = fn.__name__
            s = score_opportunity(name, cat, name in season, used.get(name, 0), weights.get(name))
            ranked.append({"format": name, "category": cat, "in_season": name in season, **s})
    ranked.sort(key=lambda r: -r["total"])
    boosts = {r["format"]: 1.08 for r in ranked if r["in_season"]}
    brief = {"date": f"{today:%Y-%m-%d}", "season_formats": season, "format_boosts": boosts, "top": ranked[:10],
             "basis": "editorial seasonal calendar + channel history; no external demand data"}
    studio.db.set("research_brief", brief, now)
    month_key = {"topic": f"Seasonal opportunities {today:%B %Y}", "source": "editorial judgement", "source_url": None, "date": f"{today:%Y-%m-01}",
                 "confidence": "low", "findings": "In-season formats this month: " + ", ".join(season),
                 "recommended_action": "Give these formats a small (8 %) preference when the story department picks a draft.", "tags": ["seasonal", "opportunity"]}
    added += add_finding(studio.db, month_key, now, kind="opportunity", scores={r["format"]: r["total"] for r in ranked[:10]})
    total = studio.db.scalar("SELECT COUNT(*) FROM research")
    return AgentReport("research", task["key"], "success",
                       output={"new_entries": added, "entries_total": total, "season_formats": season, "top_formats": [r["format"] for r in ranked[:5]]},
                       evidence=[{"sourced_entries": studio.db.scalar("SELECT COUNT(*) FROM research WHERE source != 'editorial judgement'")},
                                 {"brief": "kv:research_brief"}],
                       next_action="story department reads research_brief")
