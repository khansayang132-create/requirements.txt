"""Script Intelligence: language, emotion, voiceover parameters and a 0-100 quality score.

The judge is deterministic: the same script always gets the same score, and every score comes
with the evidence behind it (the issues it found). An optional LLM can add notes on top, but it
never changes the numbers."""
from __future__ import annotations

import re
from collections import Counter

from .textutil import EN_STOP, ID_STOP, sentence_language, split_sentences, words

EMOTIONS: dict[str, dict[str, set[str]]] = {
    "happiness": {"en": {"happy", "joy", "smile", "glad", "love", "fun", "laugh", "wonderful", "delight", "enjoy"},
                  "id": {"senang", "bahagia", "gembira", "tertawa", "seru", "lucu", "suka", "ceria", "asyik"}},
    "sadness": {"en": {"sad", "miss", "lost", "cry", "tears", "alone", "pain", "hurt", "sorry", "goodbye", "lonely"},
                "id": {"sedih", "rindu", "kangen", "menangis", "nangis", "sendiri", "sakit", "kehilangan", "berat", "takut"}},
    "excitement": {"en": {"amazing", "incredible", "wow", "now", "new", "finally", "unbelievable", "huge", "exciting", "discover"},
                   "id": {"luar", "biasa", "wow", "akhirnya", "baru", "keren", "hebat", "sekarang", "ternyata", "kejutan"}},
    "confidence": {"en": {"will", "can", "sure", "proven", "trust", "guarantee", "best", "strong", "ready", "certain"},
                   "id": {"pasti", "yakin", "bisa", "terbukti", "percaya", "terbaik", "siap", "kuat", "jaminan"}},
    "authority": {"en": {"must", "required", "important", "rule", "never", "always", "responsibility", "warning", "attention"},
                  "id": {"harus", "wajib", "penting", "aturan", "jangan", "selalu", "tanggung", "jawab", "perhatian"}},
    # Emotion words only: topic words (marriage, husband, nikah, suami) say what a story is about,
    # not how it should feel, and would tag every LSKhan-style story as romance.
    "romance": {"en": {"heart", "darling", "forever", "romantic", "kiss", "beloved", "sweetheart", "adore"},
                "id": {"sayang", "selamanya", "romantis", "mesra", "rindu-rinduan", "kekasih", "pujaan"}},
    "professional": {"en": {"solution", "service", "company", "client", "quality", "performance", "team", "business", "results"},
                     "id": {"solusi", "layanan", "perusahaan", "klien", "kualitas", "kinerja", "tim", "bisnis", "hasil"}},
    "documentary": {"en": {"history", "century", "years", "region", "species", "nature", "ancient", "culture", "population"},
                    "id": {"sejarah", "abad", "tahun", "wilayah", "alam", "kuno", "budaya", "penduduk", "tradisi"}},
    "commercial": {"en": {"buy", "sale", "offer", "discount", "free", "order", "store", "price", "shop", "deal", "today"},
                   "id": {"beli", "diskon", "promo", "gratis", "pesan", "toko", "harga", "murah", "belanja", "sekarang"}},
}

# Voiceover targets per dominant intent: words per minute, pitch, intensity.
INTENT_PARAMS = {
    "happiness": (165, "mid-high", "medium"), "sadness": (125, "low", "soft"),
    "excitement": (180, "high", "strong"), "confidence": (155, "mid", "medium-strong"),
    "authority": (140, "low", "strong"), "romance": (130, "mid-low", "soft"),
    "professional": (150, "mid", "medium"), "documentary": (140, "mid-low", "medium"),
    "commercial": (170, "mid-high", "strong"), "neutral": (155, "mid", "medium"),
}

UNNATURAL = {
    "en": [r"\bopen the light\b", r"\bclose the light\b", r"\bmore better\b", r"\bvery much like\b",
           r"\balready (eat|go|finish)\b", r"\bmake a photo\b", r"\bhow to say\b", r"\bso very\b",
           r"\bdiscuss about\b", r"\breturn back\b"],
    "id": [r"\badalah merupakan\b", r"\bsangat \w+ sekali\b", r"\bdi mana (kita|saya) bisa\b",
           r"\buntuk dapat\b", r"\bmelakukan (pembelian|pembayaran|pengecekan)\b",
           r"\bpara \w+-\w+\b", r"\bdemi untuk\b", r"\bagar supaya\b", r"\bsejak dari\b"],
}
FILLERS = {"um", "uh", "erm", "hmm", "eee", "emm", "anu"}
SECOND_PERSON = {"you", "your", "you're", "kamu", "anda", "kalian", "kau"}
IMPERATIVE = {"discover", "try", "imagine", "listen", "look", "join", "get", "start", "watch", "coba", "bayangkan",
              "dengarkan", "lihat", "ayo", "yuk", "mulai", "tonton", "cari"}
EMPHASIS_HINTS = {"never", "always", "only", "best", "first", "special", "free", "now", "today", "important",
                  "secret", "truth", "ternyata", "satu-satunya", "pertama", "rahasia", "penting", "gratis",
                  "terbaik", "selalu", "jangan", "salah"}


def _clamp(v: float) -> int:
    return int(max(0, min(100, round(v))))


def detect_language(text: str) -> dict:
    sentences = split_sentences(text)
    tags = [sentence_language(s) for s in sentences]
    counts = Counter(t for t in tags if t != "unknown")
    total = sum(counts.values()) or 1
    share = {k: round(v / total, 2) for k, v in counts.items()}
    langs = {t for t in tags if t in ("en", "id")}
    is_mixed = counts.get("mixed", 0) > 0 or len(langs) > 1
    primary = max(("en", "id"), key=lambda k: counts.get(k, 0) + counts.get("mixed", 0) * 0.5)
    if not counts:
        primary = "unknown"
    unnatural = []
    for lang, patterns in UNNATURAL.items():
        for pat in patterns:
            for m in re.finditer(pat, text, re.I):
                unnatural.append({"text": m.group(0), "language": lang,
                                  "hint": "reads like a literal translation"})
    difficult = []
    for w in dict.fromkeys(words(text)):
        reasons = []
        if re.fullmatch(r"\d[\d.,]*", w):
            reasons.append("digits: spell out for speech")
        elif len(w) >= 13:
            reasons.append("very long word")
        elif re.search(r"[bcdfghjklmnpqrstvwxz]{4,}", w.lower()):
            reasons.append("consonant cluster")
        elif re.fullmatch(r"[A-Z]{2,5}", w):
            reasons.append("acronym: decide letters or word")
        if reasons:
            difficult.append({"word": w, "reasons": reasons})
    symbols = sorted(set(re.findall(r"[%&@#$/+=*<>]|https?://\S+", text)))
    return {
        "primary": primary,
        "is_mixed": is_mixed,
        "share": share,
        "sentence_languages": [{"sentence": s, "language": t} for s, t in zip(sentences, tags)],
        "unnatural_phrases": unnatural,
        "difficult_words": difficult[:30],
        "symbols": symbols,
    }


def detect_emotion(text: str) -> dict:
    tokens = [w.lower() for w in words(text)]
    scores = {e: 0.0 for e in EMOTIONS}
    for e, lex in EMOTIONS.items():
        vocab = lex["en"] | lex["id"]
        scores[e] = sum(t in vocab for t in tokens)
    scores["excitement"] += text.count("!") * 1.5
    scores["sadness"] += text.count("...") * 0.5 + text.count("…") * 0.5
    total = sum(scores.values())
    if total == 0:
        return {"dominant": "neutral", "intensity": 20, "scores": {e: 0 for e in scores}}
    dominant = max(scores, key=scores.get)
    density = total / max(len(tokens), 1)
    intensity = _clamp(25 + density * 400 + text.count("!") * 5)
    return {"dominant": dominant, "intensity": intensity,
            "scores": {e: round(v / total * 100) for e, v in scores.items()}}


def emphasis_candidates(sentence: str, limit: int = 2) -> list[str]:
    ws = words(sentence)
    picks = [w for w in ws if w.lower() in EMPHASIS_HINTS]
    picks += [w for w in ws if re.fullmatch(r"\d[\d.,]*", w)]
    picks += [w for w in ws[1:] if w[:1].isupper() and w.lower() not in EN_STOP | ID_STOP and len(w) > 3]
    return list(dict.fromkeys(picks))[:limit]


def voiceover_parameters(text: str, emotion: dict, language: dict) -> dict:
    sentences = split_sentences(text)
    lengths = [len(words(s)) for s in sentences] or [0]
    wpm, pitch, intensity = INTENT_PARAMS.get(emotion["dominant"], INTENT_PARAMS["neutral"])
    total_words = sum(lengths)
    breathing, pauses = [], []
    for i, s in enumerate(sentences):
        n = len(words(s))
        if n > 14:
            breathing.append({"sentence": i, "after_word": n // 2, "reason": "long sentence: breathe mid-way"})
        end = s.rstrip()[-1:] if s.rstrip() else "."
        ms = {"?": 550, "!": 500, "…": 800}.get(end, 450)
        if s.rstrip().endswith("..."):
            ms = 800
        pauses.append({"sentence": i, "after_ms": ms})
    difficult = len(language["difficult_words"])
    pron = _clamp(difficult / max(total_words, 1) * 400 + len(language["symbols"]) * 8)
    return {
        "speaking_speed_wpm": wpm,
        "estimated_duration_s": round(total_words / wpm * 60 + sum(p["after_ms"] for p in pauses) / 1000, 1),
        "pitch": pitch,
        "vocal_intensity": intensity,
        "emotional_intensity": emotion["intensity"],
        "sentence_rhythm": {"mean_words": round(sum(lengths) / len(lengths), 1),
                            "min_words": min(lengths), "max_words": max(lengths),
                            "variation": round(_std(lengths), 1)},
        "breathing_points": breathing,
        "pauses": pauses,
        "emphasis": [{"sentence": i, "words": emphasis_candidates(s)} for i, s in enumerate(sentences)],
        "pronunciation_difficulty": pron,
    }


def _std(xs: list[int]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


def quality(text: str, language: dict) -> dict:
    sentences = split_sentences(text)
    tokens = words(text)
    n_words = len(tokens) or 1
    lengths = [len(words(s)) for s in sentences] or [0]
    issues: dict[str, list[str]] = {k: [] for k in ("grammar", "structure", "repetition", "clarity", "flow",
                                                    "engagement", "suitability")}

    # Grammar (mechanical checks a voice actor would trip on).
    if re.search(r" {2,}", text):
        issues["grammar"].append("double spaces")
    if re.search(r"\s[,.!?;:]", text):
        issues["grammar"].append("space before punctuation")
    for s in sentences:
        if s[:1].islower():
            issues["grammar"].append(f"sentence starts lowercase: “{s[:30]}”")
        if s[-1:] not in ".!?…\"'”":
            issues["grammar"].append(f"missing end punctuation: “{s[-30:]}”")
    for m in re.finditer(r"\b(\w+)\s+\1\b", text, re.I):
        if m.group(1).lower() not in {"very", "so", "bye", "ha"}:
            issues["grammar"].append(f"repeated word “{m.group(0)}”")
    if language["primary"] == "en" and re.search(r"\bi\b", text):
        issues["grammar"].append("lowercase “i” as a pronoun")
    if text.count("(") != text.count(")") or text.count('"') % 2:
        issues["grammar"].append("unbalanced brackets or quotes")
    issues["grammar"] += [f"unnatural phrase “{u['text']}”" for u in language["unnatural_phrases"]]

    long = [s for s, n in zip(sentences, lengths) if n > 25]
    issues["structure"] += [f"long sentence ({len(words(s))} words): “{s[:40]}…”" for s in long]
    if len(sentences) > 3 and _std(lengths) < 2:
        issues["structure"].append("sentences all the same length: monotonous rhythm")

    content = [t.lower() for t in tokens if t.lower() not in EN_STOP | ID_STOP and len(t) > 3]
    for w, c in Counter(content).items():
        if c >= 3 and c / n_words > 0.04:
            issues["repetition"].append(f"“{w}” used {c} times")
    dup = [s for s, c in Counter(s.lower() for s in sentences).items() if c > 1]
    issues["repetition"] += [f"sentence repeated: “{s[:40]}”" for s in dup]
    fillers = [t for t in tokens if t.lower() in FILLERS]
    if fillers:
        issues["repetition"].append(f"filler words: {', '.join(sorted(set(fillers)))}")

    avg_word = sum(len(t) for t in tokens) / n_words
    avg_sent = sum(lengths) / len(lengths)
    if avg_word > 6.5:
        issues["clarity"].append(f"long words on average ({avg_word:.1f} letters)")
    if avg_sent > 20:
        issues["clarity"].append(f"long sentences on average ({avg_sent:.0f} words)")

    conversational = sum(t.lower() in SECOND_PERSON for t in tokens) + text.count("?")
    if len(sentences) > 2 and conversational == 0:
        issues["flow"].append("no direct address or questions: may sound like reading")
    if any(n > 30 for n in lengths):
        issues["flow"].append("a sentence too long to say in one breath")

    first = sentences[0] if sentences else ""
    hooky = "?" in first or any(w.lower() in IMPERATIVE | EMPHASIS_HINTS for w in words(first))
    if not hooky:
        issues["engagement"].append("opening line has no hook (question, surprise or call to action)")
    if not any(t.lower() in SECOND_PERSON for t in tokens):
        issues["engagement"].append("never speaks to the listener (you / kamu)")
    if len(sentences) > 3 and not any(s.endswith("?") for s in sentences[-2:]) and not any(
            w.lower() in IMPERATIVE for w in words(" ".join(sentences[-2:]))):
        issues["engagement"].append("no closing question or call to action")

    if language["symbols"]:
        issues["suitability"].append(f"symbols that must be spoken: {' '.join(language['symbols'][:6])}")
    digits = [d["word"] for d in language["difficult_words"] if d["reasons"][0].startswith("digits")]
    if digits:
        issues["suitability"].append(f"numbers written as digits: {', '.join(digits[:6])}")
    if re.search(r"\(.*?\)", text):
        issues["suitability"].append("text in brackets is hard to voice")

    weights = {"grammar": 8, "structure": 10, "repetition": 10, "clarity": 12, "flow": 15, "engagement": 15,
               "suitability": 10}
    scores = {k: _clamp(100 - weights[k] * len(v)) for k, v in issues.items()}
    scores["clarity"] = _clamp(scores["clarity"] - max(0, avg_sent - 15) * 1.5)
    overall_w = {"grammar": 0.15, "structure": 0.12, "repetition": 0.1, "clarity": 0.15, "flow": 0.15,
                 "engagement": 0.15, "suitability": 0.18}
    overall = _clamp(sum(scores[k] * w for k, w in overall_w.items()))
    advice = {
        "grammar": "Fix punctuation and capitalisation so the reader knows where sentences end.",
        "structure": "Split sentences over 25 words; vary sentence length.",
        "repetition": "Replace repeated words, drop fillers and duplicate sentences.",
        "clarity": "Prefer short, common words and sentences under 20 words.",
        "flow": "Write the way you speak: address the listener, keep each sentence to one breath.",
        "engagement": "Open with a hook and close with a question or call to action.",
        "suitability": "Spell out numbers and symbols; avoid brackets.",
    }
    return {
        "score": overall,
        "parameters": {k: {"score": scores[k], "issues": issues[k][:8],
                           "advice": advice[k] if issues[k] else "Good."} for k in issues},
    }


def judge(text: str, llm=None) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("script is empty")
    language = detect_language(text)
    emotion = detect_emotion(text)
    result = {
        "language": language,
        "emotion": emotion,
        "voiceover": voiceover_parameters(text, emotion, language),
        "quality": quality(text, language),
        "stats": {"words": len(words(text)), "sentences": len(split_sentences(text)), "characters": len(text)},
    }
    result["score"] = result["quality"]["score"]
    if llm is not None:
        result["llm_notes"] = llm.notes(text, language["primary"])
    return result
