"""Subtitles from the production timeline (sentence start/end measured on the mastered file).

Long sentences are split into cues of at most two lines of 42 characters; a sentence's time is
shared between its cues in proportion to their length."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

MAX_LINE, MAX_LINES = 42, 2


def cues(timeline: list[dict]) -> list[dict]:
    out = []
    for t in timeline:
        text = " ".join(t["text"].split())
        lines = textwrap.wrap(text, MAX_LINE) or [""]
        chunks = [lines[i:i + MAX_LINES] for i in range(0, len(lines), MAX_LINES)]
        total = sum(len(" ".join(c)) for c in chunks) or 1
        start, span = t["start_s"], max(0.05, t["end_s"] - t["start_s"])
        for c in chunks:
            dur = span * len(" ".join(c)) / total
            out.append({"index": len(out) + 1, "start_s": round(start, 3), "end_s": round(start + dur, 3),
                        "text": "\n".join(c), "sentence": t["index"]})
            start += dur
    return out


def _ts(s: float, sep: str) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d}{sep}{ms:03d}"


def write_all(cue_list: list[dict], out_dir: Path, stem: str = "subtitles") -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    srt = "\n".join(f"{c['index']}\n{_ts(c['start_s'], ',')} --> {_ts(c['end_s'], ',')}\n{c['text']}\n" for c in cue_list)
    vtt = "WEBVTT\n\n" + "\n".join(f"{_ts(c['start_s'], '.')} --> {_ts(c['end_s'], '.')}\n{c['text']}\n" for c in cue_list)
    paths = {"srt": out_dir / f"{stem}.srt", "vtt": out_dir / f"{stem}.vtt", "json": out_dir / f"{stem}.json",
             "txt": out_dir / f"{stem}.txt"}
    paths["srt"].write_text(srt, encoding="utf-8")
    paths["vtt"].write_text(vtt, encoding="utf-8")
    paths["json"].write_text(json.dumps(cue_list, ensure_ascii=False, indent=1), encoding="utf-8")
    paths["txt"].write_text("\n".join(c["text"].replace("\n", " ") for c in cue_list) + "\n", encoding="utf-8")
    return paths


def validate(cue_list: list[dict], duration_s: float) -> list[str]:
    problems, prev = [], 0.0
    for c in cue_list:
        if c["start_s"] < prev - 1e-3:
            problems.append(f"cue {c['index']} starts before the previous one ends")
        if c["end_s"] <= c["start_s"]:
            problems.append(f"cue {c['index']} has no duration")
        if c["end_s"] > duration_s + 0.05:
            problems.append(f"cue {c['index']} ends after the audio ({c['end_s']} > {duration_s})")
        prev = c["end_s"]
    return problems
