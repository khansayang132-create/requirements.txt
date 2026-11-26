#!/usr/bin/env python3
"""Transfer TOOL_1's output (an LSKhan Studio plan document) into TOOL_2's input (nova.daily scenes).

    python3 transfer.py <plan.json> <draft.json>

Writes one entry per scene and flags every line that still holds a [placeholder] with
"needs_rewrite": true. The agent must rewrite those lines (never invent personal facts) and save the
final list before running nova.daily, which refuses any line containing "[".
Prints a JSON summary. Standard library only; uses NOVA's cleaner when the repo is present."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "nova"))
try:
    from nova.lskhan import TYPE_EMOTION, UPBEAT, clean_say  # same rules as the NOVA app
except Exception:  # NOVA not importable: minimal fallback with the same mapping
    TYPE_EMOTION = {"lucu": "happiness", "budaya": "happiness", "keluarga": "happiness", "seri": "neutral",
                    "edukasi": "professional", "emosional": "sadness", "misteri": "documentary",
                    "realita": "neutral", "debat": "confidence", "islami": "documentary"}
    UPBEAT = {"happiness", "confidence"}

    def clean_say(say: str, lang: str = "") -> str:
        s = say.replace("→", ",")
        if lang == "both":
            s = re.sub(r"\s*\((?=[^()]*[A-Za-z])[^()]{3,}\)", "", s)
        return re.sub(r"\s{2,}", " ", s).strip(" ,")

PLACEHOLDER = re.compile(r"\[([^\[\]]{2,400})\]")


def transfer(doc: dict) -> dict:
    doc = doc.get("data", doc) if isinstance(doc.get("data"), dict) else doc
    plan = doc.get("plan") or {}
    scenes = plan.get("scenes") or []
    if not scenes:
        raise ValueError("plan has no scenes")
    base = TYPE_EMOTION.get(str(plan.get("type", "")).strip().lower(), "neutral")
    out = []
    for i, s in enumerate(scenes):
        say = str(s.get("say", "")).strip()
        if not say:
            continue
        holes = [m.group(1).strip() for m in PLACEHOLDER.finditer(say)]
        entry = {"label": str(s.get("t", f"Scene {i + 1}")),
                 "text": clean_say(say, str(doc.get("lang", ""))),
                 "emotion": "excitement" if i == 0 and base in UPBEAT else base}
        if holes:
            entry["needs_rewrite"] = True
            entry["placeholders"] = holes
        out.append(entry)
    return {"title": plan.get("title", ""), "type": plan.get("type", ""), "scenes": out,
            "flagged": sum(1 for e in out if e.get("needs_rewrite"))}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    try:
        result = transfer(json.loads(Path(argv[1]).read_text()))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    Path(argv[2]).write_text(json.dumps(result["scenes"], ensure_ascii=False, indent=1))
    print(json.dumps({"title": result["title"], "type": result["type"], "scenes": len(result["scenes"]),
                      "flagged": result["flagged"], "draft": argv[2]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
