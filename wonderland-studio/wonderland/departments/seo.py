"""SEO department: honest, readable metadata for each episode.

What it writes: title, description, tags, up to three hashtags, the playlist, the YouTube
category and the cover frame. What it will not do: stuff keywords, promise anything the
video does not show, ask children to like or subscribe, or claim search demand it has not
measured. Keyword choices come from the story itself (its topics and learning goal) plus the
research database; no search-volume numbers are used because none are measured here.

One thing may vary per episode: the variable of the running experiment (see
``improvement.py``), so that its effect can be measured cleanly.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..protocol import AgentReport, PermanentError
from . import compliance

CATEGORY_SEO = {
    "A": {"about": "colors, shapes and numbers", "tags": ["learn colors", "shapes for kids", "counting for kids", "preschool learning"], "hashtag": "#PreschoolLearning"},
    "B": {"about": "gentle animal adventures", "tags": ["animal stories for kids", "nature for kids", "kids adventure"], "hashtag": "#KidsStories"},
    "C": {"about": "friendship and kindness", "tags": ["kindness for kids", "friendship stories", "social emotional learning"], "hashtag": "#Kindness"},
    "D": {"about": "good everyday habits", "tags": ["healthy habits for kids", "daily routine for kids", "good habits"], "hashtag": "#GoodHabits"},
    "E": {"about": "original rhymes to sing and move to", "tags": ["kids songs", "nursery rhymes style", "action songs for kids"], "hashtag": "#KidsSongs"},
    "F": {"about": "calm bedtime stories", "tags": ["bedtime stories for kids", "calm cartoon", "goodnight story"], "hashtag": "#BedtimeStories"},
    "G": {"about": "letters and first words", "tags": ["abc for kids", "learn the alphabet", "phonics for kids"], "hashtag": "#ABC"},
    "H": {"about": "everyday discoveries", "tags": ["science for kids", "why questions", "learning about nature"], "hashtag": "#ScienceForKids"},
}
BASE_TAGS = ["preschool", "toddler learning", "cartoon for kids", "educational cartoon"]
MAX_TAGS = 14
MAX_TAG_CHARS = 380          # YouTube allows about 500 characters of tags in total; stay well inside


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def series_title(universe: dict, series_id: str, category: str) -> str:
    for s in universe.get("recurring_series", []):
        if s["id"] == series_id:
            return s["title"]
    return f"{universe['brand']['universe']}: {CATEGORY_SEO[category]['about'].capitalize()}"


def build_metadata(story: dict, universe: dict, cfg: dict, cover: Path | None = None, variant: dict | None = None) -> dict:
    """Pure function: story → metadata dict. ``variant`` carries the experiment assignment, if any."""
    brand = universe["brand"]
    cat = story["category"]
    seo = CATEGORY_SEO[cat]
    variant = variant or {}
    opts = {"title_style": "plain", "hashtag_count": 3, "description_lead": "summary", **(variant.get("settings") or {})}

    title = _clean(story["title"])
    if opts["title_style"] == "branded" and len(title) + len(brand["channel_name"]) + 3 <= 100:
        title = f"{title} | {brand['channel_name']}"

    names = {c["id"]: c for c in universe["characters"]}
    cast = [f"{names[c]['name']} the {names[c]['species']}" for c in story.get("cast", []) if c in names]
    lead = [_clean(story["summary"]), f"What children practice: {_clean(story['learning_goal'])}"]
    if opts["description_lead"] == "learning_goal":
        lead.reverse()
    hashtags = ["#Shorts", seo["hashtag"], "#" + re.sub(r"[^A-Za-z]", "", brand["universe"])][: int(opts["hashtag_count"])]
    lines = [
        *lead,
        "",
        f"With: {', '.join(cast)}." if cast else "",
        f"{brand['channel_name']}: {brand['promise']}",
        "",
        "A short original cartoon about " + seo["about"] + ". Every character, story, voice track, song and sound is made by this studio.",
        "",
        " ".join(hashtags),
    ]
    description = "\n".join(line for i, line in enumerate(lines) if line or (i and lines[i - 1])).strip()

    tags: list[str] = []
    for t in [*story.get("topics", [])[:6], *seo["tags"], *(n.split(" the ")[0] for n in cast), brand["universe"].lower(), *BASE_TAGS]:
        t = _clean(str(t)).lower()
        if t and t not in tags and len(t) <= 30:
            tags.append(t)
    while tags and (len(tags) > MAX_TAGS or sum(len(t) + 1 for t in tags) > MAX_TAG_CHARS):
        tags.pop()

    pub = cfg.get("publishing", {})
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "playlist": series_title(universe, story.get("series", ""), cat),
        "category_id": str((pub.get("youtube_category") or {}).get(cat, "27")),
        "default_language": pub.get("default_language", "en"),
        "made_for_kids": bool(pub.get("made_for_kids", True)),
        "cover": str(cover) if cover else None,
        "experiment": {k: variant[k] for k in ("name", "variable", "variant") if k in variant} or None,
        "basis": "written from the story's own topics and learning goal; no search-volume data was used",
    }


def channel_seo(universe: dict) -> dict:
    """Channel-level SEO the owner pastes into YouTube Studio when creating the channel."""
    brand = universe["brand"]
    chars = ", ".join(f"{c['name']} the {c['species']}" for c in universe["characters"])
    about = (f"{brand['tagline']} {brand['promise']}\n\nMeet {chars} in {brand['universe']}. New short cartoons every day: colors, shapes and numbers, "
             "letters, kind friends, good habits, gentle adventures, original rhymes and calm bedtime stories.\n\n"
             "Everything here is original: our own characters, stories, music and sounds. Made for kids.")
    keywords = ["preschool cartoons", "toddler learning videos", "learn colors", "abc for kids", "counting for kids", "bedtime stories for kids",
                "kindness for kids", "kids songs", brand["universe"].lower()]
    return {"channel_name": brand["channel_name"], "handle_candidates": brand.get("handle_candidates", []), "about": about, "keywords": keywords,
            "audience": "Yes, this channel is made for kids", "language": brand.get("language", "en"),
            "playlists": [{"title": s["title"], "category": s["category"]} for s in universe.get("recurring_series", [])]}


def handle_seo(studio, task: dict, ep: dict) -> AgentReport:
    from . import improvement

    if not ep or not ep.get("story"):
        raise PermanentError("episode has no story")
    cover = Path(ep["dir"]) / "cover.png" if ep.get("dir") else None
    variant = improvement.assignment(studio, ep)
    defaults = studio.db.get("metadata_defaults", {}) or {}
    if defaults:
        variant = {**variant, "settings": {**defaults, **(variant.get("settings") or {})}}
    meta = build_metadata(ep["story"], studio.universe, studio.cfg, cover if cover and cover.is_file() else None, variant)
    verdict = compliance.review_metadata(meta)
    if not verdict["ok"]:
        raise PermanentError("metadata failed its own review: " + "; ".join(verdict["errors"][:4]))
    studio.db.update_episode(ep["id"], studio.now(), metadata=meta)
    return AgentReport("seo", task["key"], "success",
                       output={"title": meta["title"], "tags": len(meta["tags"]), "hashtags": meta["hashtags"], "playlist": meta["playlist"],
                               "category_id": meta["category_id"], "experiment": meta["experiment"]},
                       evidence=[{"title_chars": len(meta["title"])}, {"description_chars": len(meta["description"])}, {"metadata_review": "passed"}],
                       next_action="compliance")
