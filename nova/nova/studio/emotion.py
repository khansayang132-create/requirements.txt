"""ENGINE 04: Emotional intelligence.

Reads the whole narrative first (where it starts, where it peaks, where it lands), then every
sentence. Each sentence gets an emotion from a fixed library, an intensity, and a full delivery
plan. Intensity is not loudness: a heartbroken line at 85/100 is slower, lower and quieter.

Emotions come from three sources, in this order of trust: a user edit, the optional local LLM
(validated against the library), the lexicon below. Consecutive intensities are smoothed so the
script does not swing from line to line, and lines with no emotional cue stay calm.

Every emotion is rendered through controls a voice engine really has (rate, pitch, pitch range,
volume, pauses; on Chatterbox, pitch range drives its exaggeration). Nothing here claims an
engine can whisper or sound sarcastic natively; `rendering` says how each line is realised."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..script_judge import emphasis_candidates
from ..textutil import split_sentences, words

# name: (engine emotion, delivery, speed, pitch direction, rate, pitch st, range, volume dB,
#        pause before ms, pause after ms, breathing)
LIBRARY: dict[str, tuple] = {
    "happy":         ("happiness", "bright and smiling", "medium", "rising", 1.04, 1.5, 1.25, 0.5, 0, 400, "normal"),
    "sad":           ("sadness", "soft and heavy", "slow", "falling", 0.88, -1.5, 0.8, -2.0, 200, 700, "slow breath before"),
    "heartbroken":   ("sadness", "soft and fragile", "slow", "falling", 0.84, -2.0, 0.75, -3.0, 300, 1000, "audible breath before"),
    "romantic":      ("romance", "warm and intimate", "slow", "level", 0.9, -0.5, 1.1, -1.5, 100, 600, "soft breath"),
    "nostalgic":     ("sadness", "warm and wistful", "slow", "falling", 0.9, -0.5, 0.9, -1.0, 200, 700, "slow breath"),
    "angry":         ("authority", "tight and firm", "medium", "falling", 1.0, -1.0, 1.15, 1.5, 0, 400, "short breath"),
    "frustrated":    ("confidence", "tense and clipped", "medium", "level", 1.0, -0.5, 1.1, 0.5, 0, 450, "short breath"),
    "disappointed":  ("sadness", "flat and tired", "slow", "falling", 0.9, -1.0, 0.85, -1.5, 150, 600, "sigh before"),
    "hopeful":       ("happiness", "warm and lifting", "medium", "rising", 0.98, 1.0, 1.15, 0.0, 150, 600, "breath before"),
    "inspirational": ("confidence", "warm and uplifting", "medium", "rising", 0.97, 1.0, 1.2, 1.0, 200, 700, "full breath before"),
    "confident":     ("confidence", "steady and clear", "medium", "level", 0.98, 0.0, 1.1, 1.0, 0, 450, "normal"),
    "determined":    ("confidence", "firm and resolved", "medium", "level", 0.96, -0.5, 1.05, 1.0, 100, 500, "steady breath"),
    "fearful":       ("sadness", "hushed and unsteady", "medium", "rising", 1.02, 0.5, 0.9, -2.0, 100, 500, "quick shallow breath"),
    "curious":       ("happiness", "light and questioning", "medium", "rising", 1.0, 1.0, 1.2, 0.0, 0, 500, "normal"),
    "compassionate": ("romance", "gentle and caring", "slow", "level", 0.9, -0.5, 1.0, -1.5, 100, 600, "soft breath"),
    "grateful":      ("happiness", "warm and sincere", "medium", "falling", 0.95, 0.5, 1.05, -0.5, 100, 600, "soft breath"),
    "peaceful":      ("documentary", "calm and still", "slow", "level", 0.9, -0.5, 0.85, -1.5, 200, 700, "slow breath"),
    "vulnerable":    ("sadness", "quiet and open", "slow", "falling", 0.88, -1.0, 0.85, -2.5, 250, 800, "breath before"),
    "excited":       ("excitement", "energetic and bright", "fast", "rising", 1.1, 3.0, 1.45, 1.5, 0, 350, "quick breath"),
    "powerful":      ("authority", "full and commanding", "medium", "falling", 0.94, -1.5, 1.1, 2.0, 200, 700, "full breath before"),
    "whispering":    ("romance", "very quiet and close (rendered as low volume and slow pace)", "slow", "level",
                      0.88, -1.0, 0.8, -6.0, 150, 600, "soft breath"),
    "reflective":    ("documentary", "quiet and thoughtful", "slow", "falling", 0.92, -0.5, 0.9, -1.0, 150, 650, "slow breath"),
    "comforting":    ("romance", "soft and reassuring", "slow", "level", 0.9, -0.5, 1.0, -1.0, 100, 600, "soft breath"),
    "sarcastic":     ("confidence", "dry, with a lifted stress (approximated by pitch range)", "medium", "rising",
                      1.0, 0.5, 1.3, 0.0, 0, 450, "normal"),
    "suspenseful":   ("documentary", "low and drawn out", "slow", "level", 0.88, -1.0, 0.9, -1.0, 300, 900, "held breath"),
    "serious":       ("professional", "measured and plain", "medium", "level", 0.96, 0.0, 0.95, 0.0, 0, 450, "normal"),
}
NEUTRAL = "serious"

LEXICON: dict[str, set[str]] = {
    "heartbroken": {"hancur", "patah", "kehilangan", "pergi selamanya", "heartbroken", "shattered", "lost forever"},
    "sad": {"sedih", "menangis", "air mata", "tangis", "sepi", "sendiri", "kesepian", "duka", "sad", "tears", "cry",
            "alone", "lonely", "grief"},
    "nostalgic": {"dulu", "kenangan", "teringat", "masa kecil", "remember", "memories", "used to"},
    "hopeful": {"harapan", "berharap", "semoga", "suatu hari", "esok", "besok", "pagi baru", "hope", "someday",
                "tomorrow", "new morning", "chance", "kesempatan"},
    "determined": {"terus", "tidak menyerah", "pantang menyerah", "berjuang", "bertahan", "bangkit", "tetap",
                   "keep going", "never give up", "fight", "fighting", "stand up", "kuat"},
    "grateful": {"syukur", "bersyukur", "alhamdulillah", "terima kasih", "grateful", "thankful", "thank you"},
    "compassionate": {"peluk", "sayang", "kasih", "peduli", "care", "embrace", "hug"},
    "romantic": {"cinta", "rindu", "kekasih", "suamiku", "istriku", "love", "darling", "miss you"},
    "fearful": {"takut", "khawatir", "cemas", "afraid", "scared", "worried", "fear"},
    "angry": {"marah", "kesal", "benci", "angry", "furious", "hate"},
    "frustrated": {"capek", "lelah", "letih", "tired", "exhausted", "frustrated"},
    "disappointed": {"kecewa", "disappointed", "let down"},
    "inspirational": {"inspirasi", "mimpi", "impian", "percaya", "dream", "believe", "inspire"},
    "peaceful": {"tenang", "damai", "peaceful", "calm", "quiet"},
    "excited": {"seru", "wow", "akhirnya", "amazing", "finally", "excited"},
    "curious": {"kenapa", "mengapa", "bagaimana", "apa yang", "why", "how", "what if"},
    "reflective": {"terkadang", "kadang", "ternyata", "hidup", "sometimes", "life", "realize"},
    "powerful": {"tidak ada yang bisa", "nothing can", "unstoppable", "luar biasa"},
    "comforting": {"tidak apa-apa", "kamu tidak sendiri", "it's okay", "you are not alone"},
}


@dataclass
class SentenceDirection:
    index: int
    text: str
    emotion: str
    intensity: int
    vocal_energy: str
    speed: str
    pitch_direction: str
    delivery: str
    pause_before_ms: int
    pause_after_ms: int
    emphasis: list[str]
    breathing: str
    transition_from_previous: str
    transition_to_next: str
    source: str
    rendering: dict = field(default_factory=dict)
    prosody: dict = field(default_factory=dict)
    engine_emotion: str = "neutral"

    def to_dict(self) -> dict:
        return asdict(self)


def _lexicon_emotion(sentence: str) -> tuple[str, int]:
    s = " " + sentence.lower() + " "
    best, score = NEUTRAL, 0
    for emo, cues in LEXICON.items():
        hits = sum(1 for c in cues if re.search(r"(?<![a-z])" + re.escape(c) + r"(?![a-z])", s))
        if hits > score:
            best, score = emo, hits
    if sentence.rstrip().endswith("!") and best == NEUTRAL:
        best, score = "excited", 1
    if sentence.rstrip().endswith("?") and best == NEUTRAL:
        best, score = "curious", 1
    return best, score


def narrative_arc(sentences: list[str]) -> dict:
    """Whole-story pass: where it opens, peaks and lands, from the lexicon over thirds."""
    n = len(sentences)
    thirds = [sentences[: max(1, n // 3)], sentences[n // 3: max(n // 3 + 1, 2 * n // 3)], sentences[2 * n // 3:]]
    labels = []
    for part in thirds:
        counts: dict[str, int] = {}
        for s in part:
            e, sc = _lexicon_emotion(s)
            if sc:
                counts[e] = counts.get(e, 0) + sc
        labels.append(max(counts, key=counts.get) if counts else NEUTRAL)
    # Where the story lands is its last line that carries a feeling, not the third's majority.
    for s_ in reversed(thirds[2]):
        e, sc = _lexicon_emotion(s_)
        if sc:
            labels[2] = e
            break
    shape = "rising" if labels[-1] in ("hopeful", "inspirational", "determined", "grateful", "powerful") else \
        "falling" if labels[-1] in ("sad", "heartbroken", "disappointed") else "level"
    return {"opening": labels[0], "middle": labels[1], "ending": labels[2], "shape": shape, "sentences": n}


def _energy(emotion: str, intensity: int) -> str:
    calm = {"sad", "heartbroken", "nostalgic", "peaceful", "vulnerable", "whispering", "reflective",
            "comforting", "compassionate", "romantic", "suspenseful", "disappointed"}
    if emotion in calm:
        return "low" if intensity >= 40 else "low-medium"
    return "high" if intensity >= 75 else "medium" if intensity >= 40 else "low-medium"


def _transition(prev: str | None, cur: str) -> str:
    if prev is None:
        return "opening line: start in this mood"
    if prev == cur:
        return f"continue {cur}"
    return f"shift from {prev} to {cur}: change pace and colour across the pause, not abruptly"


def _plan(i: int, text: str, emotion: str, intensity: int, source: str, mode_scale: float) -> SentenceDirection:
    eng, delivery, speed, pitch_dir, rate, pitch, rng, vol, pb, pa, breath = LIBRARY[emotion]
    k = intensity / 100 * mode_scale  # intensity scales distance from neutral delivery, not loudness
    prosody = {"rate": round(1 + (rate - 1) * k, 3), "pitch_semitones": round(pitch * k, 2),
               "pitch_range": round(1 + (rng - 1) * k, 3), "volume_db": round(vol * k, 2)}
    end = text.rstrip()[-1:] if text.strip() else "."
    pa = int(pa * (0.6 + 0.6 * intensity / 100)) + (150 if end in "?…" else 0)
    return SentenceDirection(
        index=i, text=text, emotion=emotion, intensity=intensity, vocal_energy=_energy(emotion, intensity),
        speed=speed, pitch_direction=pitch_dir, delivery=delivery, pause_before_ms=int(pb * intensity / 100),
        pause_after_ms=pa, emphasis=emphasis_candidates(text, limit=2), breathing=breath,
        transition_from_previous="", transition_to_next="", source=source, engine_emotion=eng, prosody=prosody,
        rendering={"rate": "engine speed (time-stretch on Chatterbox)", "pitch": "engine or pitch shift",
                   "pitch_range": "intonation range (Chatterbox: exaggeration)", "volume": "gain",
                   "pauses": "silence between segments"})


def _link(dirs: list[SentenceDirection]) -> None:
    for i, d in enumerate(dirs):
        d.transition_from_previous = _transition(dirs[i - 1].emotion if i else None, d.emotion)
        d.transition_to_next = "closing line: let it settle" if i == len(dirs) - 1 else \
            _transition(d.emotion, dirs[i + 1].emotion).replace("shift from", "lead into").split(":")[0]
    if dirs:
        dirs[-1].pause_after_ms = 0


def analyze(text: str, mode: str = "natural", llm=None, language: str = "id") -> dict:
    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("no sentences to direct")
    arc = narrative_arc(sentences)
    labels: list[tuple[str, int, str]] = []
    llm_labels = _llm_labels(sentences, llm, language) if llm else None
    for i, s in enumerate(sentences):
        lex, score = _lexicon_emotion(s)
        if llm_labels and i < len(llm_labels) and llm_labels[i]:
            emo, inten = llm_labels[i]
            labels.append((emo, inten, "llm"))
        elif score:
            labels.append((lex, min(90, 45 + 15 * score), "lexicon"))
        else:
            labels.append((NEUTRAL, 30, "default"))
    # Smooth: no jump of more than 30 points between neighbours; calm lines stay calm.
    smoothed = []
    for i, (e, v, src) in enumerate(labels):
        if i and abs(v - smoothed[-1][1]) > 30:
            v = smoothed[-1][1] + (30 if v > smoothed[-1][1] else -30)
        smoothed.append((e, int(max(10, min(100, v))), src))
    scale = {"natural": 0.85, "professional": 0.6, "expressive": 1.15}.get(mode, 0.85)
    dirs = [_plan(i, s, e, v, src, scale) for i, (s, (e, v, src)) in enumerate(zip(sentences, smoothed))]
    _link(dirs)
    return {"arc": arc, "mode": mode, "sentences": [d.to_dict() for d in dirs]}


def edit(directions: list[dict], index: int, emotion: str | None = None, intensity: int | None = None,
         mode: str = "natural", **overrides) -> list[dict]:
    """Change one sentence without touching the others (only neighbour transitions update)."""
    if emotion is not None and emotion not in LIBRARY:
        raise ValueError(f"unknown emotion {emotion!r}; use one of {sorted(LIBRARY)}")
    d = directions[index]
    scale = {"natural": 0.85, "professional": 0.6, "expressive": 1.15}.get(mode, 0.85)
    new = _plan(index, d["text"], emotion or d["emotion"], int(intensity if intensity is not None else d["intensity"]),
                "user", scale).to_dict()
    for k in ("pause_before_ms", "pause_after_ms", "emphasis", "delivery"):
        if k in overrides and overrides[k] is not None:
            new[k] = overrides[k]
    out = [dict(x) for x in directions]
    out[index] = new
    objs = [SentenceDirection(**x) for x in out]
    _link(objs)
    if index == len(out) - 1 and "pause_after_ms" in overrides:
        objs[-1].pause_after_ms = 0
    return [o.to_dict() for o in objs]


def to_script(directions: list[dict]) -> str:
    lines = []
    for d in directions:
        lines += [f"[EMOTION: {d['emotion'].upper()}]", f"[INTENSITY: {d['intensity']}/100]",
                  f"[DELIVERY: {d['delivery'].upper()}]", f"[SPEED: {d['speed'].upper()}]",
                  f"[PITCH: {d['pitch_direction'].upper()}]"]
        if d["pause_before_ms"]:
            lines.append(f"[PAUSE BEFORE: {d['pause_before_ms']}ms]")
        if d["emphasis"]:
            lines.append(f"[EMPHASIS: {', '.join(d['emphasis'])}]")
        lines += [f"\"{d['text']}\"", f"[PAUSE: {d['pause_after_ms']}ms]", ""]
    return "\n".join(lines).strip()


def _llm_labels(sentences: list[str], llm, language: str) -> list[tuple[str, int] | None] | None:
    system = ("You are an emotional performance director for voiceovers. Read the whole script first, then label "
              "each sentence with ONE emotion from this list: " + ", ".join(LIBRARY) +
              ". Give an intensity 10-100 (how strongly the feeling shows, not loudness). Most narration lines are "
              "calm; do not make every line dramatic. Return {\"labels\": [{\"i\": 0, \"emotion\": ..., \"intensity\": ...}, ...]}")
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    try:
        data = llm.chat_json(system, numbered, max_tokens=60 * len(sentences) + 200, temperature=0.2)
    except Exception:
        return None
    out: list[tuple[str, int] | None] = [None] * len(sentences)
    for item in (data.get("labels") or []) if isinstance(data, dict) else []:
        try:
            i, emo, inten = int(item["i"]), str(item["emotion"]).lower().strip(), int(item["intensity"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= i < len(sentences) and emo in LIBRARY:
            out[i] = (emo, max(10, min(100, inten)))
    return out if any(out) else None


def word_count(text: str) -> int:
    return len(words(text))
