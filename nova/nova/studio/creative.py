"""ENGINE 01: Creative intelligence. Understands an idea and develops concepts.

Uses the local LLM (any OpenAI-compatible endpoint). Every field it returns is validated and
clipped; nothing it says is trusted as fact. Factual content types are flagged so later stages
never invent statistics, quotes, hadith or dates: the script writer is told to keep such content
general or to leave a [source needed] marker, which the QA stage then reports."""
from __future__ import annotations

from ..script_judge import detect_language

CONTENT_TYPES = ["motivational", "emotional", "romantic", "documentary", "islamic", "business", "educational",
                 "promotional", "lifestyle", "personal", "entertainment"]
FACTUAL_TYPES = {"documentary", "islamic", "educational", "business", "promotional"}
PLATFORMS = ["tiktok", "instagram_reels", "youtube_shorts", "youtube", "podcast", "facebook"]
LANGUAGES = {"id": "Bahasa Indonesia", "en": "English", "ur": "Urdu (Urdu script)", "roman-ur": "Roman Urdu",
             "ar": "Arabic"}
KEYWORDS = {
    "islamic": ["allah", "islam", "doa", "sholat", "ramadan", "quran", "hadis", "iman", "dakwah"],
    "romantic": ["cinta", "love", "rindu", "pasangan", "suami", "istri", "nikah"],
    "motivational": ["semangat", "sukses", "motivasi", "bangkit", "jangan menyerah", "motivation"],
    "emotional": ["berjuang", "keluarga", "sedih", "air mata", "ibu", "struggle", "family"],
    "business": ["bisnis", "usaha", "brand", "startup", "business", "jualan"],
    "educational": ["cara", "tips", "belajar", "how to", "learn", "fakta", "facts"],
    "promotional": ["produk", "promo", "diskon", "product", "launch", "beli"],
    "documentary": ["sejarah", "history", "dokumenter", "documentary"],
}


def _guess_type(text: str) -> str:
    t = text.lower()
    scores = {k: sum(t.count(w) for w in ws) for k, ws in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "personal"


def _language(text: str, requested: str | None) -> str:
    if requested in LANGUAGES:
        return requested
    primary = detect_language(text)["primary"]
    return primary if primary in LANGUAGES else "en"


def _clip(v, n: int = 400) -> str:
    return str(v or "").strip()[:n]


def analyze_intent(idea: str, llm=None, language: str | None = None, extra: dict | None = None) -> dict:
    """Purpose, audience, structure, perspective, direction, emotional journey, language, reaction."""
    idea = idea.strip()
    if not idea:
        raise ValueError("an idea is required")
    lang = _language(idea, language)
    ctype = _guess_type(idea)
    base = {"idea": idea, "language": lang, "content_type": ctype, "factual": ctype in FACTUAL_TYPES,
            "source": "heuristic", "extra": extra or {}}
    if not llm:
        return base | {"purpose": "", "audience": "", "structure": "hook → story → turn → message → close",
                       "perspective": "", "direction": "", "emotional_journey": [], "desired_reaction": ""}
    system = ("You are a creative director for short narrated videos. Analyse the idea. Return JSON with keys: "
              "purpose, audience, audience_psychology, structure, perspective (first/second/third person), "
              "direction, emotional_journey (list of 3-5 emotions in order), desired_reaction, content_type "
              f"(one of {', '.join(CONTENT_TYPES)}), factual (true if it needs real facts). Write values in "
              f"{LANGUAGES[lang]}.")
    user = f"Idea: {idea}\nExtra context: {extra or {}}"
    data = llm.chat_json(system, user, max_tokens=700)
    ct = str(data.get("content_type", ctype)).lower()
    journey = data.get("emotional_journey") or []
    return base | {
        "source": "llm", "content_type": ct if ct in CONTENT_TYPES else ctype,
        "factual": bool(data.get("factual")) or (ct in FACTUAL_TYPES),
        "purpose": _clip(data.get("purpose")), "audience": _clip(data.get("audience")),
        "audience_psychology": _clip(data.get("audience_psychology")), "structure": _clip(data.get("structure")),
        "perspective": _clip(data.get("perspective"), 60), "direction": _clip(data.get("direction")),
        "emotional_journey": [_clip(e, 40) for e in journey][:6] if isinstance(journey, list) else [],
        "desired_reaction": _clip(data.get("desired_reaction")),
    }


def concepts(intent: dict, llm, n: int = 3, duration_s: int = 60) -> list[dict]:
    if not llm:
        raise RuntimeError("concept generation needs the local LLM (set it up in Settings)")
    lang = LANGUAGES[intent["language"]]
    rule = ("Do not state facts, numbers, quotes, hadith or dates unless they are common knowledge; never invent them."
            if intent.get("factual") else "This is creative storytelling: invented characters are fine, but do not "
            "present them as real people or real events.")
    system = (f"You develop {n} different concepts for one narrated video. Each concept needs: title, angle, "
              "audience, hook (the first spoken line, under 15 words), message, emotional_direction, "
              f"duration_s (about {duration_s}), platform (one of {', '.join(PLATFORMS)}). {rule} Write in {lang}. "
              'Return {"concepts": [...]}.')
    user = (f"Idea: {intent['idea']}\nPurpose: {intent.get('purpose')}\nAudience: {intent.get('audience')}\n"
            f"Emotional journey: {intent.get('emotional_journey')}")
    data = llm.chat_json(system, user, max_tokens=350 * n + 200, temperature=0.8)
    out = []
    for c in (data.get("concepts") or [])[:n] if isinstance(data, dict) else []:
        if not isinstance(c, dict) or not c.get("title") or not c.get("hook"):
            continue
        try:
            dur = int(float(c.get("duration_s", duration_s)))
        except (TypeError, ValueError):
            dur = duration_s
        plat = str(c.get("platform", "tiktok")).lower().replace(" ", "_")
        out.append({"title": _clip(c["title"], 120), "angle": _clip(c.get("angle")), "audience": _clip(c.get("audience")),
                    "hook": _clip(c["hook"], 200), "message": _clip(c.get("message")),
                    "emotional_direction": _clip(c.get("emotional_direction"), 200),
                    "duration_s": max(10, min(900, dur)), "platform": plat if plat in PLATFORMS else "tiktok"})
    if not out:
        raise RuntimeError("the LLM returned no usable concepts")
    return out
