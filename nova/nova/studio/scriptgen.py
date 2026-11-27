"""ENGINE 02: Script generation with a duration engine.

Spoken length is estimated from language-specific speaking rates (words per minute of
unhurried narration). The writer asks the LLM for a target word count, measures the result and
asks it to expand or shorten (at most twice) until it is within 12% of the target; if it still
is not, the result says so instead of pretending. Long scripts are written section by section."""
from __future__ import annotations

from ..textutil import split_sentences, words
from .creative import LANGUAGES

# Unhurried narration, words per minute. Indonesian words are longer (more syllables) than English.
SPEECH_WPM = {"id": 120, "en": 145, "ur": 130, "roman-ur": 130, "ar": 110}
DURATIONS = [15, 30, 45, 60, 90, 120, 300, 600]
SECTIONS = ["hook", "context", "development", "build-up", "key message", "conclusion", "call to action"]
SHARE = {"hook": 0.08, "context": 0.14, "development": 0.30, "build-up": 0.20, "key message": 0.14,
         "conclusion": 0.10, "call to action": 0.04}
TOLERANCE = 0.12


def estimate_seconds(text: str, language: str = "id", pause_s: float = 0.45) -> float:
    n = len(words(text))
    return round(n / SPEECH_WPM.get(language, 130) * 60 + pause_s * max(0, len(split_sentences(text)) - 1), 1)


def target_words(seconds: float, language: str, sentences_hint: int | None = None) -> int:
    pauses = 0.45 * (sentences_hint if sentences_hint else max(1, seconds / 5))
    return max(12, int((seconds - pauses) / 60 * SPEECH_WPM.get(language, 130)))


def _rules(intent: dict) -> str:
    base = ("Write for the ear: short and medium sentences mixed, natural spoken vocabulary, no headings, no stage "
            "directions, no emoji, numbers spelled out. ")
    if intent.get("factual"):
        base += ("Use only common-knowledge facts. Never invent statistics, quotes, hadith, studies or dates; if a "
                 "point needs a source, keep it general. ")
    else:
        base += "This is a story: characters may be invented, but never present them as a real person. "
    return base


def generate(intent: dict, concept: dict | None, seconds: float, llm, include_cta: bool = False) -> dict:
    if not llm:
        raise RuntimeError("script generation needs the local LLM (set it up in Settings)")
    lang = intent["language"]
    want = target_words(seconds, lang)
    parts = [p for p in SECTIONS if include_cta or p != "call to action"]
    brief = (f"Idea: {intent['idea']}\nPurpose: {intent.get('purpose', '')}\nAudience: {intent.get('audience', '')}\n"
             f"Emotional journey: {intent.get('emotional_journey', '')}\n")
    if concept:
        brief += f"Title: {concept['title']}\nOpening hook: {concept['hook']}\nMessage: {concept.get('message', '')}\n"
    system = (f"You are a professional screenwriter of narrated videos in {LANGUAGES[lang]}. Write natural, "
              f"idiomatic {LANGUAGES[lang]} (never a literal translation). " + _rules(intent))
    log = []
    if want <= 350:
        user = (brief + f"\nWrite the full narration in about {want} words, flowing through: {', '.join(parts)}. "
                "Return only the narration text.")
        text = llm.chat(system, user, max_tokens=int(want * 3 + 200), temperature=0.7).strip()
    else:  # long form: one call per section keeps the model on target
        pieces = []
        for p in parts:
            n = max(20, int(want * SHARE[p] / sum(SHARE[q] for q in parts)))
            user = (brief + f"\nSo far:\n{' '.join(pieces)[-1500:]}\n\nWrite only the '{p}' part next, about {n} "
                    "words, continuing naturally. Return only the narration text.")
            pieces.append(llm.chat(system, user, max_tokens=int(n * 3 + 150), temperature=0.7).strip())
        text = "\n\n".join(pieces)
    text = _clean(text)
    for attempt in range(2):
        got = len(words(text))
        log.append({"attempt": attempt, "words": got, "target_words": want})
        if abs(got - want) / want <= TOLERANCE:
            break
        verb = "Expand" if got < want else "Shorten"
        user = (f"{verb} this narration to about {want} words. Keep the hook, the story, the message and the "
                f"language. Return only the narration.\n\n{text}")
        text = _clean(llm.chat(system, user, max_tokens=int(want * 3 + 200), temperature=0.5))
    got = len(words(text))
    est = estimate_seconds(text, lang)
    ok = abs(est - seconds) / seconds <= 0.2
    return {"text": text, "language": lang, "words": got, "target_words": want, "target_s": seconds,
            "estimated_s": est, "within_target": ok, "attempts": log,
            "note": "" if ok else f"estimated {est}s vs requested {seconds}s after 2 corrections"}


def _clean(text: str) -> str:
    import re
    t = re.sub(r"^\s*(#+|\*\*?).*?$", "", text, flags=re.M)  # headings the model may add anyway
    t = re.sub(r"\*\*|__|`", "", t)
    t = re.sub(r"\((?:hook|context|development|build-up|key message|conclusion|call to action)\)", "", t, flags=re.I)
    t = re.sub(r"^\s*(?:Narrator|Narasi|Voice ?over)\s*:\s*", "", t, flags=re.M | re.I)
    return re.sub(r"\n{3,}", "\n\n", t).strip()
