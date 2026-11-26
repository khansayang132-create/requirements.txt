"""Automatic script enhancement in three modes, with a meaning guard.

Every change is a named rule with before/after evidence. Rules only fix form (spelling-out,
punctuation, sentence length, fillers, contractions); none of them adds or removes a claim.
`meaning_check` compares content words before and after and the result is returned with the
enhancement, so the user can see the message was preserved."""
from __future__ import annotations

import difflib
import re

from .script_judge import detect_language
from .textutil import EN_STOP, ID_STOP, numbers_to_words, split_sentences, words

MODES = ("natural", "professional", "expressive")

CONTRACT = {
    "do not": "don't", "does not": "doesn't", "did not": "didn't", "is not": "isn't", "are not": "aren't",
    "was not": "wasn't", "cannot": "can't", "can not": "can't", "will not": "won't", "it is": "it's",
    "I am": "I'm", "you are": "you're", "we are": "we're", "they are": "they're", "that is": "that's",
    "let us": "let's", "I will": "I'll", "you will": "you'll", "we will": "we'll", "I have": "I've",
}
EXPAND = {v: k for k, v in CONTRACT.items() if k != "can not"}
SOFT_FILLERS = {"en": ["basically", "actually", "literally", "you know", "kind of", "sort of"],
                "id": ["sebenarnya sih", "pokoknya", "gitu deh"]}
HARD_FILLERS = r"\b(um+|uh+|erm+|hmm+|e{3,}|em{2,}|anu)\b[,]?\s*"
TWIST = {"en": ["but", "however", "suddenly", "then", "until"], "id": ["tapi", "ternyata", "namun", "tiba-tiba", "sampai"]}
SPLIT_AT = [", and ", ", but ", ", so ", ", which ", ", because ", ", dan ", ", tapi ", ", jadi ", ", karena ",
            ", sehingga ", ", yang ", "; "]
SYMBOLS = {"en": {"&": " and ", "+": " plus ", "@": " at ", "=": " equals "},
           "id": {"&": " dan ", "+": " plus ", "@": " di ", "=": " sama dengan "}}


def _content(text: str, language: str) -> set[str]:
    norm = numbers_to_words(text, language).lower()
    for short, full in EXPAND.items():
        norm = norm.replace(short.lower(), full.lower())
    return {w.lower().strip("'") for w in words(norm)
            if w.lower() not in EN_STOP | ID_STOP and len(w) > 2 and w.lower() not in
            {"basically", "actually", "literally", "pokoknya", "anu"}}


def meaning_check(original: str, enhanced: str, language: str) -> dict:
    a, b = _content(original, language), _content(enhanced, language)
    kept = len(a & b) / len(a) if a else 1.0
    added = sorted(b - a)
    return {"content_words_kept": round(kept, 3), "new_content_words": added[:20],
            "preserved": kept >= 0.85 and len(added) <= max(3, len(a) // 8)}


def _split_long(sentence: str, max_words: int) -> list[str]:
    if len(words(sentence)) <= max_words:
        return [sentence]
    mid = len(sentence) / 2
    best = None
    for marker in SPLIT_AT:
        for m in re.finditer(re.escape(marker), sentence, re.I):
            if best is None or abs(m.start() - mid) < abs(best[0] - mid):
                best = (m.start(), m.end(), marker)
    if best is None:
        return [sentence]
    start, end, marker = best
    left = sentence[:start].rstrip(",;") + "."
    right_word = sentence[start:end].strip(" ,;")
    right = sentence[end:]
    if right_word in ("which", "yang"):  # keep the relative clause attached, just add a breath
        return [sentence]
    right = (right_word.capitalize() + " " + right) if right_word else right[:1].upper() + right[1:]
    return _split_long(left, max_words) + _split_long(right.strip(), max_words)


def enhance(text: str, mode: str = "natural", llm=None) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    original = (text or "").strip()
    if not original:
        raise ValueError("script is empty")
    lang_info = detect_language(original)
    lang = lang_info["primary"] if lang_info["primary"] in ("en", "id") else "en"
    changes: list[dict] = []

    def apply(rule: str, pattern: str, repl, t: str, flags=re.I) -> str:
        new = re.sub(pattern, repl, t, flags=flags)
        if new != t:
            for a, b in _changed_spans(t, new):
                changes.append({"rule": rule, "before": a, "after": b})
        return new

    t = re.sub(r"[ \t]+", " ", original)
    t = apply("spacing", r"\s+([,.!?;:])", r"\1", t)
    t = apply("filler words", HARD_FILLERS, "", t)
    t = apply("capitalisation", r"(^|[.!?…]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t, flags=0)
    t = apply("repeated word", r"\b(?!(?:very|so|ha)\b)(\w+)(\s+\1\b)+", r"\1", t)
    if mode == "professional":
        for f in SOFT_FILLERS[lang]:
            t = apply("filler words", rf",?\s*\b{re.escape(f)}\b,?", "", t)
    t = apply("URL readability", r"https?://(www\.)?", "", t)
    for sym, spoken in SYMBOLS[lang].items():
        t = apply("symbol to words", rf"\s*{re.escape(sym)}\s*", spoken, t)
    before = t
    t = numbers_to_words(t, lang)
    if t != before:
        for a, b in _changed_spans(before, t):
            changes.append({"rule": "numbers to words", "before": a, "after": b})
    if lang == "en":
        t = apply("capital I", r"\bi\b", "I", t, flags=0)
        table = CONTRACT if mode == "natural" else EXPAND if mode == "professional" else {}
        for src, dst in table.items():
            t = apply("contractions" if mode == "natural" else "formal wording",
                      rf"\b{re.escape(src)}\b", dst, t, flags=0)

    # Sentence-level rules.
    sentences = []
    seen = set()
    max_words = {"natural": 20, "professional": 22, "expressive": 18}[mode]
    for s in split_sentences(t):
        key = s.lower().strip(" .!?")
        if key in seen:
            changes.append({"rule": "duplicate sentence removed", "before": s, "after": ""})
            continue
        seen.add(key)
        s = s[:1].upper() + s[1:]
        if s[-1:] not in ".!?…\"'”":
            s += "?" if re.match(r"(?i)(what|why|how|who|where|when|is|are|do|does|apa|kenapa|bagaimana|siapa|kapan|di mana)\b", s) else "."
        parts = _split_long(s, max_words)
        if len(parts) > 1:
            changes.append({"rule": "long sentence split", "before": s, "after": " ".join(parts)})
        sentences.extend(parts)

    if mode == "expressive":
        out = []
        for s in sentences:
            for w in TWIST[lang]:
                m = re.match(rf"({w})\b,?\s*", s, re.I)
                if m and not s.startswith(m.group(1) + "…"):
                    new = f"{m.group(1)}… {s[m.end():]}"
                    changes.append({"rule": "dramatic pause before twist", "before": s, "after": new})
                    s = new
                    break
            out.append(s)
        sentences = out

    enhanced = " ".join(sentences)
    source = "rules"
    llm_report = None
    if llm is not None:
        try:
            candidate = llm.rewrite(enhanced, mode, lang).strip()
            check = meaning_check(original, candidate, lang)
            if candidate and check["preserved"]:
                enhanced, source = candidate, "llm+rules"
                changes.append({"rule": "LLM rewrite (meaning check passed)", "before": "", "after": ""})
            llm_report = {"accepted": source == "llm+rules", "check": check}
        except Exception as exc:
            llm_report = {"accepted": False, "error": type(exc).__name__}

    return {
        "mode": mode,
        "language": lang,
        "original": original,
        "enhanced": enhanced,
        "changes": changes,
        "diff": word_diff(original, enhanced),
        "meaning": meaning_check(original, enhanced, lang),
        "source": source,
        "llm": llm_report,
    }


def _changed_spans(a: str, b: str) -> list[tuple[str, str]]:
    aw, bw = a.split(), b.split()
    spans = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, aw, bw).get_opcodes():
        if op != "equal":
            spans.append((" ".join(aw[i1:i2]), " ".join(bw[j1:j2])))
    return spans[:20]


def word_diff(a: str, b: str) -> list[dict]:
    aw, bw = a.split(), b.split()
    ops = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, aw, bw).get_opcodes():
        if op == "equal":
            ops.append({"op": "equal", "text": " ".join(aw[i1:i2])})
        else:
            if i2 > i1:
                ops.append({"op": "delete", "text": " ".join(aw[i1:i2])})
            if j2 > j1:
                ops.append({"op": "insert", "text": " ".join(bw[j1:j2])})
    return ops
