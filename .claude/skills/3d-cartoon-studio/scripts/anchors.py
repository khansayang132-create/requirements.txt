#!/usr/bin/env python3
"""Print the CHARACTER ANCHOR block (section 3 of SKILL.md) for each character in the bible.

    python3 .claude/skills/3d-cartoon-studio/scripts/anchors.py            # all characters
    python3 .claude/skills/3d-cartoon-studio/scripts/anchors.py bobo       # one
    ... --universe path/to/universe.yaml

Reads wonderland-studio/config/universe.yaml; needs PyYAML.
"""
import argparse
import sys
from pathlib import Path

import yaml

DEFAULT = Path(__file__).resolve().parents[4] / "wonderland-studio" / "config" / "universe.yaml"
STYLE = "modern 3D toon, soft rounded forms, cel-shaded with rim light"


def anchor(c: dict) -> str:
    p, col, cl = c["proportions"], c["colors"], c["clothing"]
    return "\n".join([
        "CHARACTER ANCHOR:",
        f"{c['name'].upper()} ({c['id']}), {c['species']}, {c['age_representation']},",
        f"build: {p['build']}; head is {round(p['head_ratio'] * 100)}% of height,",
        f"face: {c['facial_features']}",
        f"colors: body {col['body']}, belly {col.get('belly', '-')}, accent {col.get('accent', '-')},",
        f"signature: {cl['note']} ({cl['accessory']}, {cl['color']}),",
        f"personality: {', '.join(c['personality'])}; signature moves: {', '.join(c['signature_moves'])},",
        f"visual style: {STYLE}",
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("character", nargs="?")
    ap.add_argument("--universe", default=str(DEFAULT))
    a = ap.parse_args()
    chars = yaml.safe_load(open(a.universe, encoding="utf-8"))["characters"]
    if a.character:
        chars = [c for c in chars if c["id"] == a.character]
        if not chars:
            print(f"no character {a.character!r}", file=sys.stderr)
            return 2
    print("\n\n".join(anchor(c) for c in chars))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
