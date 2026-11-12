from __future__ import annotations

from pathlib import Path


def _ts(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[dict], out: Path, max_words: int = 7) -> Path:
    """cues: [{"text","start","end"}]. Long cues are split into readable chunks by word timing share."""
    lines, n = [], 0
    for c in cues:
        words = c["text"].split()
        chunks = [words[i:i + max_words] for i in range(0, len(words), max_words)] or [[]]
        span = (c["end"] - c["start"]) / max(1, len(words))
        t = c["start"]
        for ch in chunks:
            n += 1
            end = min(c["end"], t + span * len(ch))
            lines.append(f"{n}\n{_ts(t)} --> {_ts(end)}\n{' '.join(ch)}\n")
            t = end
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
