"""Story intelligence: choose what to make, score it, and refuse duplicates.

For a slot the engine drafts several candidate stories (different formats, casts and
contents), reviews each with the compliance department, scores them on six
dimensions and keeps the best one that is not a repeat.

Scores are *editorial*: they are computed from the story itself and from this
channel's own history. They never claim search volume or demand — that only enters
through ``weights`` once real YouTube Analytics exist (see the improvement department).

Duplicate protection, in order:
1. the exact signature (format + parameters) may never be used twice;
2. the same format may not repeat within ``format_gap`` recent episodes;
3. the script may not be more than ``max_similarity`` similar (word 3-gram Jaccard)
   to any recent script, nor to another episode planned for the same day.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import urllib.error
import urllib.request

from ..render.environments import ENVS
from ..render.props import PROPS
from . import compliance
from .story_formats import CATEGORY_NAMES, FORMATS, Story

SCORE_WEIGHTS = {"audience_relevance": 0.2, "originality": 0.25, "educational_value": 0.2, "storytelling": 0.15,
                 "feasibility": 0.1, "brand_consistency": 0.1}
# Editorial priors per category (0-1). Replaced by measured performance when analytics exist.
EDU_PRIOR = {"A": 0.95, "G": 0.95, "H": 0.9, "D": 0.85, "C": 0.8, "B": 0.7, "E": 0.7, "F": 0.55}
RELEVANCE_PRIOR = {"A": 0.9, "E": 0.9, "G": 0.85, "D": 0.8, "C": 0.8, "B": 0.8, "F": 0.75, "H": 0.75}


def signature(story: Story | dict) -> str:
    d = story if isinstance(story, dict) else story.as_dict()
    blob = json.dumps([d["format"], d.get("params", {})], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def shingles(text: str, k: int = 3) -> set[str]:
    words = re.findall(r"[a-z']+", text.lower())
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


def similarity(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def score_story(story: Story, history: list[dict], weights: dict | None = None) -> dict:
    """Six transparent 0-1 scores and their weighted total."""
    script = story.script()
    pool_h = history[-40:] + [h for h in history[:-40] if h["format"] == story.format]
    max_sim = max((similarity(script, h["script"]) for h in pool_h), default=0.0)
    speakers = {b["speaker"] for b in story.beats}
    envs = {b["env"] for b in story.beats}
    dialogue = sum(1 for b in story.beats if b["speaker"] != "narrator") / max(1, len(story.beats))
    perf = (weights or {}).get(story.format, 1.0)
    scores = {
        "audience_relevance": round(min(1.0, RELEVANCE_PRIOR.get(story.category, 0.7) * perf), 3),
        "originality": round(1.0 - max_sim, 3),
        "educational_value": EDU_PRIOR.get(story.category, 0.6),
        "storytelling": round(min(1.0, 0.35 + 0.3 * dialogue + 0.12 * len(speakers) + 0.08 * len(envs)), 3),
        "feasibility": 1.0 if 7 <= len(story.beats) <= 16 else 0.6,
        "brand_consistency": 1.0 if story.beats[-1].get("overlay", {}) and story.beats[-1]["overlay"]["style"] == "end" else 0.7,
    }
    scores["total"] = round(sum(scores[k] * w for k, w in SCORE_WEIGHTS.items()), 4)
    scores["basis"] = "editorial scoring from the script and channel history; no search-volume data used"
    return scores


class StoryEngine:
    def __init__(self, universe: dict, cfg: dict | None = None):
        self.uni = universe
        cfg = cfg or {}
        self.format_gap = int(cfg.get("format_gap", 6))
        self.max_similarity = float(cfg.get("max_similarity", 0.62))
        self.candidates = int(cfg.get("candidates", 6))
        self.known_chars = {c["id"] for c in universe["characters"]}

    def review(self, story: Story) -> dict:
        return compliance.review_story(story.as_dict(), set(PROPS), self.known_chars, set(ENVS))

    def generate(self, categories: list[str], seed: str, history: list[dict], same_day: list[dict] | None = None,
                 weights: dict | None = None) -> tuple[Story, dict]:
        """Return (story, report). ``history`` rows: {"signature","format","script","cast"} oldest first."""
        same_day = same_day or []
        used = {h["signature"] for h in history}
        recent_formats = [h["format"] for h in history[-self.format_gap:]]
        day_leads = [h["cast"][0] for h in same_day if h.get("cast")]
        pool = [(cat, f) for cat in categories for f in FORMATS[cat]]
        fresh = [(c, f) for c, f in pool if f.__name__ not in recent_formats] or pool
        drafts, rejected = [], []
        for attempt in range(self.candidates * 6):
            rng = random.Random(f"{seed}:{attempt}")
            cat, fn = rng.choice(fresh)
            try:
                story = fn(rng, self.uni)
            except Exception as exc:  # noqa: BLE001 - a broken format must not stop the day
                rejected.append({"format": fn.__name__, "reason": f"format error: {type(exc).__name__}: {exc}"})
                continue
            sig = signature(story)
            if sig in used or any(sig == d[2] for d in drafts):
                rejected.append({"format": story.format, "reason": "exact repeat of an earlier episode"})
                continue
            verdict = self.review(story)
            if not verdict["ok"]:
                rejected.append({"format": story.format, "reason": "compliance: " + "; ".join(verdict["errors"][:3])})
                continue
            script = story.script()
            # compare with the last 40 scripts AND with every earlier script of the same format
            pool_h = history[-40:] + [h for h in history[:-40] if h["format"] == story.format]
            sim_hist = max((similarity(script, h["script"]) for h in pool_h), default=0.0)
            sim_day = max((similarity(script, h["script"]) for h in same_day), default=0.0)
            if sim_hist > self.max_similarity or sim_day > 0.4:
                rejected.append({"format": story.format, "reason": f"too similar to an existing script ({max(sim_hist, sim_day):.2f})"})
                continue
            scores = score_story(story, history, weights)
            if story.cast and story.cast[0] in day_leads:
                scores["total"] = round(scores["total"] - 0.05, 4)   # prefer a different lead character each slot
            drafts.append((scores["total"], story, sig, scores, verdict))
            if len(drafts) >= self.candidates:
                break
        if not drafts:
            raise RuntimeError("no acceptable story could be generated: " + json.dumps(rejected[:5]))
        drafts.sort(key=lambda d: -d[0])
        total, story, sig, scores, verdict = drafts[0]
        report = {
            "signature": sig,
            "scores": scores,
            "compliance": verdict,
            "category_name": CATEGORY_NAMES[story.category],
            "candidates_considered": len(drafts),
            "candidates": [{"format": d[1].format, "title": d[1].title, "total": d[0]} for d in drafts],
            "rejected": rejected[:12],
            "provider": "grammar",
        }
        return story, report


# ------------------------------------------------------------------ optional LLM -----
LLM_SYSTEM = """You write one short original cartoon script for children aged 2-5.
Return ONLY a JSON object with keys: title, summary, learning_goal, mood, beats.
Each beat: {"speaker": "narrator" or a character id, "text": one sentence of at most 12 words,
"env": environment id, "actors": [{"id": character id, "action": action}], "items": [{"name": prop, "color": color or null,
"count": 1-6, "layout": "show"}], "overlay": null or {"text": word, "style": "word", "color": color}}.
8 to 12 beats. One small true idea. Calm and kind. No brands, no scary content, no requests to like or subscribe,
no questions about the child's name, age or home. Use only the ids you are given."""


class LLMStoryProvider:
    """Optional: draft stories with any OpenAI-compatible chat endpoint (e.g. the owner's OmniRoute).

    Enabled only when WONDERLAND_LLM_BASE_URL and WONDERLAND_LLM_MODEL are set. Every draft goes
    through the same compliance review and vocabulary validation as built-in formats; a draft that
    fails is discarded (the engine then uses a built-in format), never "fixed up" silently.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: int = 60):
        self.base_url, self.model, self.api_key, self.timeout = base_url.rstrip("/"), model, api_key, timeout

    def draft(self, category: str, universe: dict, avoid_titles: list[str]) -> Story:
        chars = [{"id": c["id"], "name": c["name"], "species": c["species"], "personality": c["personality"]} for c in universe["characters"]]
        user = json.dumps({
            "category": CATEGORY_NAMES[category], "characters": chars, "environments": sorted(ENVS), "props": sorted(PROPS),
            "actions": ["idle", "wave", "hop", "cheer", "dance", "point", "think", "nod", "look_up", "sad", "clap", "yawn", "sleep"],
            "colors": ["red", "orange", "yellow", "green", "blue", "purple", "pink"], "moods": ["bright", "adventure", "warm", "calm"],
            "do_not_repeat_titles": avoid_titles[-20:],
        })
        body = json.dumps({"model": self.model, "temperature": 0.9,
                           "messages": [{"role": "system", "content": LLM_SYSTEM}, {"role": "user", "content": user}]}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url + "/chat/completions", data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise RuntimeError(f"LLM story provider unavailable: {type(exc).__name__}") from exc
        text = data["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("LLM returned no JSON object")
        raw = json.loads(m.group(0))
        beats = []
        for b in raw.get("beats", []):
            beats.append({"speaker": b.get("speaker", "narrator"), "text": str(b.get("text", "")).strip(), "env": b.get("env", "meadow"),
                          "actors": [{"id": a.get("id"), "action": a.get("action", "idle"), "hold": None} for a in b.get("actors", [])],
                          "items": [{"name": i.get("name"), "color": i.get("color"), "count": int(i.get("count", 1)), "layout": "show",
                                     "appear": "pop"} for i in b.get("items", [])],
                          "overlay": b.get("overlay"), "fx": None, "transfer": None, "sfx": []})
        if beats:
            beats[-1]["overlay"] = {"text": universe["brand"]["end_card"], "style": "end", "color": "yellow"}
        cast = []
        for b in beats:
            for a in b["actors"]:
                if a["id"] not in cast:
                    cast.append(a["id"])
        return Story(category, "llm_original", "llm", str(raw.get("title", "")).strip(), str(raw.get("summary", "")).strip(),
                     str(raw.get("learning_goal", "")).strip(), raw.get("mood", "bright"), cast, beats, [CATEGORY_NAMES[category].lower()],
                     {"title": raw.get("title", "")})


def runway(universe: dict, history: list[dict], categories: list[str], samples: int = 40, max_similarity: float = 0.62) -> dict:
    """Lower-bound estimate of how many more unique stories each category can still produce.

    Samples each format and counts drafts that are neither an exact repeat nor too similar to
    that format's history. When a category's runway gets short the CEO raises an alert:
    it is time to write new formats (or enable the LLM provider), not to start repeating.
    """
    used = {h["signature"] for h in history}
    out = {}
    for cat in categories:
        total = 0
        for fn in FORMATS[cat]:
            seen = set()
            past = [h["script"] for h in history if h["format"] == fn.__name__]
            for i in range(samples):
                st = fn(random.Random(f"runway:{fn.__name__}:{i}"), universe)
                sig = signature(st)
                if sig in used or sig in seen:
                    continue
                if any(similarity(st.script(), p) > max_similarity for p in past):
                    continue
                seen.add(sig)
            total += len(seen)
        out[cat] = total
    return out
