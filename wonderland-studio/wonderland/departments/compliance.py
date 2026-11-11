"""Child-safety and platform-compliance department. Mandatory gate: nothing is rendered,
and nothing is uploaded, unless this module passes it.

What it enforces (sources are in the research database, topic "policy"):
* YouTube's quality principles for kids and family content: no heavily commercial
  content, nothing that encourages negative behaviour, nothing deceptively educational,
  nothing that hinders comprehension, nothing sensational or misleading.
* Made for Kids: every video is declared made for kids; the script must not ask
  children for personal information or push them to like/subscribe/comment/buy
  (comments, notifications and personalised ads are off on such videos anyway).
* Altered/synthetic content disclosure: YouTube does not require the label for clearly
  unrealistic content such as animation. The decision and its reason are recorded per
  episode; the owner can force the label on in studio.yaml.
* Gentle pacing: short sentences, a bounded number of lines, calm bedtime episodes.
"""

from __future__ import annotations

import re

MAX_WORDS_PER_LINE = 14
MAX_LINES = 20

BANNED = {
    "violence": ["kill", "killed", "die", "dead", "death", "gun", "knife", "blood", "fight", "punch", "hit you", "weapon", "war", "shoot"],
    "fear": ["monster", "ghost", "scary", "nightmare", "zombie", "witch", "haunted", "creepy", "terrifying"],
    "unsafe_imitation": ["jump off", "climb the roof", "play with fire", "matches", "run away from home", "hide from mom", "don't tell",
                         "keep it secret", "swallow", "medicine", "pills"],
    "adult": ["beer", "wine", "drunk", "cigarette", "smoke", "sexy", "kiss on the lips", "boyfriend", "girlfriend", "gambling"],
    "negative_behaviour": ["stupid", "idiot", "hate you", "shut up", "ugly", "dumb", "loser", "fat"],
    "commercial": ["buy", "purchase", "price", "sale", "sponsor", "brand new toy from", "store", "shop now", "unboxing"],
    "engagement_bait": ["subscribe", "like and", "hit the bell", "smash", "comment below", "share this video", "click", "follow us",
                        "turn on notifications"],
    "privacy": ["what is your name", "how old are you", "where do you live", "your address", "your school", "phone number",
                "send us", "tell us your"],
    "third_party_ip": ["disney", "pixar", "cocomelon", "peppa", "bluey", "paw patrol", "mickey", "elsa", "pokemon", "baby shark",
                       "blippi", "sesame", "pinkfong", "ms rachel"],
    "sensational": ["shocking", "you won't believe", "gone wrong", "insane", "crazy", "omg", "emergency", "prank"],
}

# Phrases that look like banned words but are fine in context.
ALLOWED_PHRASES = ["sun hat", "what is your favorite", "which color do you like"]


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text)


def lint_text(text: str) -> list[str]:
    """Return the list of problems in one piece of viewer-facing text (line, title, description)."""
    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    for ok in ALLOWED_PHRASES:
        low = low.replace(ok, " ")
    problems = []
    for group, terms in BANNED.items():
        for term in terms:
            if re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", low):
                problems.append(f"{group}: '{term}'")
    if text.isupper() and len(text) > 30:
        problems.append("sensational: long all-caps text")
    if text.count("!") > 3:
        problems.append("sensational: more than three exclamation marks")
    return problems


def review_story(story: dict, known_props: set[str], known_chars: set[str], known_envs: set[str]) -> dict:
    """Full content review of a story dict. Returns {"ok", "errors", "warnings", "made_for_kids", ...}."""
    errors: list[str] = []
    warnings: list[str] = []
    beats = story.get("beats", [])
    if not 6 <= len(beats) <= MAX_LINES:
        errors.append(f"story has {len(beats)} lines; expected 6-{MAX_LINES}")
    for i, b in enumerate(beats, 1):
        text = b.get("text", "")
        n = len(_words(text))
        if n == 0:
            errors.append(f"line {i}: empty")
        if n > MAX_WORDS_PER_LINE:
            errors.append(f"line {i}: {n} words (max {MAX_WORDS_PER_LINE}): {text!r}")
        for p in lint_text(text):
            errors.append(f"line {i}: {p}")
        if b.get("speaker") != "narrator" and b.get("speaker") not in known_chars:
            errors.append(f"line {i}: unknown speaker {b.get('speaker')!r}")
        if b.get("env") not in known_envs:
            errors.append(f"line {i}: unknown environment {b.get('env')!r}")
        for a in b.get("actors", []):
            if a["id"] not in known_chars:
                errors.append(f"line {i}: unknown character {a['id']!r}")
            if a.get("hold") and a["hold"]["name"] not in known_props:
                errors.append(f"line {i}: unknown held prop {a['hold']['name']!r}")
        for it in b.get("items", []):
            if it["name"] not in known_props:
                errors.append(f"line {i}: unknown prop {it['name']!r}")
        if b.get("transfer") and b["transfer"]["name"] not in known_props:
            errors.append(f"line {i}: unknown transferred prop")
    for key in ("title", "summary", "learning_goal"):
        value = story.get(key, "")
        if not value.strip():
            errors.append(f"{key}: missing")
        for p in lint_text(value):
            errors.append(f"{key}: {p}")
    if len(story.get("title", "")) > 90:
        errors.append("title: longer than 90 characters")
    # the title must be about what is actually in the video (no misleading titles)
    script = " ".join(b.get("text", "") for b in beats).lower()
    stop = {"with", "and", "the", "a", "an", "of", "to", "in", "is", "for", "from", "her", "his", "little", "what", "where",
            "why", "how", "do", "does", "should", "we", "story", "rhyme", "adventure", "routine", "bedtime", "learns"}
    names_and_overlays = script + " " + " ".join((b.get("overlay") or {}).get("text", "").lower() for b in beats)
    title_words = [w.lower().rstrip("'s") for w in _words(story.get("title", "")) if w.lower() not in stop and len(w) > 2]
    missing = [w for w in title_words if w not in names_and_overlays and w.rstrip("s") not in names_and_overlays]
    if title_words and len(missing) > len(title_words) * 0.5:
        errors.append(f"title: most title words never appear in the video ({', '.join(missing)})")
    questions = sum(1 for b in beats if b.get("text", "").strip().endswith("?"))
    if questions > 6:
        warnings.append(f"{questions} questions; keep prompts to the viewer gentle and few")
    if story.get("mood") == "calm":
        loud = [b["text"] for b in beats if b["text"].count("!") >= 2]
        if loud:
            warnings.append("calm episode has excited lines: " + "; ".join(loud[:2]))
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "made_for_kids": True,
        "made_for_kids_reason": "Preschool animation whose primary audience is children aged 2-5.",
    }


def disclosure_decision(cfg: dict, voice_provider: str) -> dict:
    """Should status.containsSyntheticMedia be set? Owner override first, then YouTube's rule."""
    forced = (cfg.get("publishing") or {}).get("contains_synthetic_media")
    if isinstance(forced, bool):
        return {"contains_synthetic_media": forced, "reason": "set explicitly in studio.yaml → publishing.contains_synthetic_media"}
    return {
        "contains_synthetic_media": False,
        "reason": ("Clearly unrealistic 2D animation with a synthetic narrator voice. YouTube requires the altered/synthetic "
                   "label only for realistic content that could be mistaken for real people, places or events; animation is "
                   f"exempt. Voice engine: {voice_provider}. Recorded so the owner can review or override."),
    }


def review_metadata(meta: dict) -> dict:
    errors = []
    for key in ("title", "description"):
        for p in lint_text(meta.get(key, "")):
            errors.append(f"{key}: {p}")
    for tag in meta.get("tags", []):
        for p in lint_text(tag):
            errors.append(f"tag {tag!r}: {p}")
    if len(meta.get("hashtags", [])) > 5:
        errors.append("more than five hashtags (keyword stuffing)")
    title = meta.get("title", "")
    if len(title) > 100:
        errors.append("title over 100 characters")
    words = [w.lower() for w in _words(title)]
    if any(words.count(w) > 2 for w in set(words) if len(w) > 3):
        errors.append("title repeats a keyword more than twice (keyword stuffing)")
    return {"ok": not errors, "errors": errors}
