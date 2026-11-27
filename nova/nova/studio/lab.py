"""ENGINE 03: Script intelligence lab - analysis, enhancement modes, sentence operations, versions.

Builds on NOVA's scorer (script_judge) and rule-based enhancer. LLM rewrites pass NOVA's
meaning check (content words kept) before they are accepted; a rejected rewrite is reported,
never silently applied. Every operation produces a new version; the original stays."""
from __future__ import annotations

import difflib
import re
from collections import Counter

from ..enhance import enhance as rule_enhance
from ..enhance import meaning_check
from ..script_judge import judge
from ..textutil import split_sentences, words
from .creative import LANGUAGES
from .scriptgen import estimate_seconds

MODES = {
    "natural": ("natural", "natural human conversation: how a real person talks to a friend"),
    "cinematic": ("expressive", "cinematic storytelling: vivid images, rhythm, scene-setting"),
    "deep_emotional": ("expressive", "deep emotional storytelling: intimate, honest, quiet power"),
    "professional": ("professional", "professional narration: clear, polished, measured"),
    "motivational": ("expressive", "motivational delivery: energy, conviction, a call to rise"),
    "documentary": ("professional", "documentary narration: factual tone, calm authority"),
    "social": ("natural", "social media engagement: a strong first line, short punchy sentences, a question"),
    "persuasive": ("professional", "persuasive business narration: benefit-led, credible, one clear ask"),
}
OPERATIONS = {
    "rewrite": "Rewrite it in this style",
    "expand": "Expand it by about 30% with more detail and feeling, without new factual claims",
    "shorten": "Shorten it by about 30%, keeping the core message",
    "simplify": "Simplify the vocabulary and sentence structure so anyone understands it at once",
    "vocabulary": "Improve word choice with more vivid, precise, natural words",
    "hook": "Rewrite only the first sentence into a stronger hook; keep the rest exactly",
    "ending": "Rewrite only the last one or two sentences into a stronger ending; keep the rest exactly",
}
DIFFICULT = re.compile(r"[^\W\d_]{14,}|\d|[%&@#/=+]|(?:[bcdfghjklmnpqrstvwxyz]{4,})", re.I)


def analyze(text: str, language: str = "id", llm=None) -> dict:
    j = judge(text)
    sents = split_sentences(text)
    lengths = [len(words(s)) for s in sents]
    toks = [w.lower() for w in words(text)]
    grams = Counter(" ".join(toks[i:i + 3]) for i in range(len(toks) - 2))
    repeated = [{"phrase": g, "count": c} for g, c in grams.most_common(10) if c > 1]
    hard = sorted({m.group(0) for m in DIFFICULT.finditer(text)})
    out = {
        "score": j["score"], "quality": j["quality"], "language": j["language"], "emotion": j["emotion"],
        "sentences": len(sents), "words": len(toks),
        "sentence_length": {"avg": round(sum(lengths) / max(1, len(lengths)), 1), "max": max(lengths or [0]),
                            "long_sentences": [s for s, n in zip(sents, lengths) if n > 22]},
        "repetition": repeated, "pronunciation_difficulty": {"items": hard[:20], "count": len(hard)},
        "estimated_s": estimate_seconds(text, language),
    }
    if llm:
        try:
            system = ("You are a script editor. Judge narrative consistency and emotional effectiveness of this "
                      "narration. Return JSON: {consistency: 0-100, emotional_effectiveness: 0-100, "
                      "natural_speech: 0-100, notes: [max 4 short notes]} in "
                      f"{LANGUAGES.get(language, 'English')}.")
            r = llm.chat_json(system, text, max_tokens=500, temperature=0.2)
            out["editor"] = {k: (max(0, min(100, int(r[k]))) if k != "notes" else [str(n)[:200] for n in r[k]][:4])
                             for k in ("consistency", "emotional_effectiveness", "natural_speech", "notes") if k in r}
        except Exception as exc:
            out["editor"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    return out


def enhance(text: str, mode: str, language: str = "id", llm=None, operation: str = "rewrite",
            sentence_index: int | None = None) -> dict:
    """Return {text, accepted, method, meaning, note}. Never edits in place."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}")
    if operation not in OPERATIONS:
        raise ValueError(f"operation must be one of {sorted(OPERATIONS)}")
    base_mode, brief = MODES[mode]
    sents = split_sentences(text)
    target = text
    if sentence_index is not None:
        if not 0 <= sentence_index < len(sents):
            raise ValueError("sentence_index out of range")
        target = sents[sentence_index]
    if not llm:
        if operation != "rewrite" or sentence_index is not None:
            raise RuntimeError(f"'{operation}' needs the local LLM; without it only the rule-based rewrite works")
        r = rule_enhance(text, base_mode)
        return {"text": r["enhanced"], "accepted": True, "method": "rules", "meaning": None,
                "note": "rule-based: grammar, numbers, long sentences, pauses"}
    system = (f"You edit narration scripts in {LANGUAGES.get(language, 'the same language')}. Style: {brief}. "
              "Keep the meaning, every fact, name and number. Do not add factual claims. Natural, idiomatic "
              "language, never a literal translation. Return only the edited text.")
    new = llm.chat(system, f"{OPERATIONS[operation]}:\n\n{target}", max_tokens=len(words(target)) * 4 + 200,
                   temperature=0.6).strip()
    new = re.sub(r"\*\*|__|`", "", new).strip().strip('"')
    full = new if sentence_index is None else " ".join(new if i == sentence_index else s for i, s in enumerate(sents))
    meaning = meaning_check(target, new, language)
    keep_needed = operation not in ("expand", "shorten", "hook", "ending")
    accepted = bool(new) and (meaning.get("preserved", False) or not keep_needed)
    return {"text": full if accepted else text, "proposal": full, "accepted": accepted, "method": "llm",
            "meaning": meaning, "note": "" if accepted else "rejected: the rewrite dropped too much of the meaning"}


def compare(a: str, b: str, language: str = "id") -> dict:
    sm = difflib.SequenceMatcher(a=words(a), b=words(b))
    changes = []
    wa, wb = words(a), words(b)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            changes.append({"op": tag, "before": " ".join(wa[i1:i2]), "after": " ".join(wb[j1:j2])})
    sa, sb = judge(a)["score"], judge(b)["score"]
    return {"similarity": round(sm.ratio(), 3), "changes": changes[:200], "score_before": sa, "score_after": sb,
            "seconds_before": estimate_seconds(a, language), "seconds_after": estimate_seconds(b, language)}
