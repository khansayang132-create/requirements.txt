"""Voice performance direction: character + line + scene context -> concrete engine controls, plus take variation.

Only controls the engines really have are produced: rate, pitch shift, pitch range, volume, pauses before/after,
emphasised words (SSML on eSpeak), length/noise scale on Piper (mapped from rate/range by the adapter).
"""

from __future__ import annotations

import random
import re

#                 rate%  pitch%  range  volume  pause_before pause_after
EMOTION = {
    "neutral":    (100, 0, 1.00, 100, 0.00, 0.10),
    "happy":      (106, 6, 1.25, 100, 0.00, 0.10),
    "excited":    (114, 10, 1.45, 105, 0.00, 0.08),
    "laughing":   (110, 8, 1.40, 100, 0.00, 0.10),
    "sad":        (86, -6, 0.70, 85, 0.15, 0.25),
    "crying":     (82, -2, 0.85, 85, 0.20, 0.30),
    "worried":    (96, -2, 0.90, 92, 0.10, 0.15),
    "angry":      (108, -4, 1.30, 110, 0.00, 0.10),
    "surprised":  (110, 12, 1.50, 105, 0.05, 0.10),
    "calm":       (92, -3, 0.80, 92, 0.05, 0.15),
    "whisper":    (90, -2, 0.60, 60, 0.05, 0.15),
}


def parse_markup(text: str) -> tuple[str, list[str]]:
    """'I *really* mean it' -> ('I really mean it', ['really'])."""
    emph = re.findall(r"\*([^*]+)\*", text)
    return re.sub(r"\*([^*]+)\*", r"\1", text), emph


def apply_pronunciation(text: str, rules: dict[str, str]) -> tuple[str, list[dict]]:
    used = []
    for word, respell in rules.items():
        pat = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
        if pat.search(text):
            text = pat.sub(respell, text)
            used.append({"word": word, "as": respell})
    return text, used


def direct(line: dict, scene: dict | None = None, intensity: float | None = None) -> dict:
    """Decide intensity, pace, pauses and emphasis for one line."""
    emo = line.get("emotion", "neutral")
    rate, pitch, rng, vol, pb, pa = EMOTION.get(emo, EMOTION["neutral"])
    k = line.get("intensity", intensity if intensity is not None else 1.0)
    text, emph = parse_markup(line["text"])
    if not emph and text.rstrip().endswith("!") and emo in ("excited", "angry", "surprised", "happy"):
        words = [w.strip(".,!?") for w in text.split() if len(w.strip(".,!?")) > 3]
        emph = words[-1:] if words else []
    if (scene or {}).get("pace") == "fast":
        rate *= 1.06
    if (scene or {}).get("pace") == "slow":
        rate *= 0.94
    c = {"emotion": emo, "intensity": k, "rate_pct": round(100 + (rate - 100) * k, 1), "pitch_shift_pct": int(round(pitch * k)),
         "range_mul": round(1 + (rng - 1) * k, 3), "volume_pct": round(100 + (vol - 100) * k, 1), "pause_before": pb, "pause_after": pa,
         "emphasis": emph, "text": text}
    if "..." in text:
        c["pause_after"] += 0.1
    return c


def variation(controls: dict, take_index: int, seed: str) -> dict:
    """Take 0 is the director's read; later takes vary pace, pitch and range a little (deterministic per seed)."""
    if take_index == 0:
        return dict(controls)
    r = random.Random(f"{seed}|{take_index}")
    c = dict(controls)
    c["rate_pct"] = round(c["rate_pct"] * r.uniform(0.93, 1.07), 1)
    c["pitch_shift_pct"] = int(c["pitch_shift_pct"] + r.randint(-3, 3))
    c["range_mul"] = round(c["range_mul"] * r.uniform(0.88, 1.12), 3)
    return c


def correct(controls: dict, defect: str) -> dict:
    """A regeneration that addresses a measured defect."""
    c = dict(controls)
    if defect == "too_short":
        c["rate_pct"] = round(c["rate_pct"] * 0.88, 1)
    elif defect == "too_long":
        c["rate_pct"] = round(c["rate_pct"] * 1.1, 1)
    elif defect == "abrupt_cutoff":
        c["pause_after"] = max(c.get("pause_after", 0), 0.25)
    elif defect == "internal_gap":
        c["text"] = c["text"].replace("...", ",")
        c["pause_after"] = max(0.1, c.get("pause_after", 0) - 0.1)
    elif defect in ("clipping",):
        c["volume_pct"] = round(c["volume_pct"] * 0.85, 1)
    return c
