#!/usr/bin/env python3
"""Make one episode end to end (development harness; the company uses `python -m wonderland`).

    python tools/make_episode.py --out /tmp/ep --categories A --seed demo1 [--format color_walk] [--backend flat]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wonderland import config, pipeline  # noqa: E402
from wonderland.departments.story import StoryEngine  # noqa: E402
from wonderland.departments.story_formats import FORMATS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--categories", default="A")
    ap.add_argument("--seed", default="demo")
    ap.add_argument("--format", help="force one story format by function name")
    ap.add_argument("--backend", default=None)
    ap.add_argument("--voices", default=None, help="comma list, e.g. espeak")
    a = ap.parse_args()
    uni, cfg = config.load_universe(), config.load_studio()
    if a.backend:
        cfg["video"]["backend"] = a.backend
    if a.voices:
        cfg["audio"]["voice_providers"] = a.voices.split(",")
    out = Path(a.out)
    if a.format:
        import random
        fn = next(f for fs in FORMATS.values() for f in fs if f.__name__ == a.format)
        story = fn(random.Random(a.seed), uni).as_dict()
    else:
        story, _ = StoryEngine(uni, cfg.get("story")).generate(list(a.categories.split(",")), a.seed, [])
        story = story.as_dict()
    rep = pipeline.produce(story, uni, cfg, out, pipeline.make_desk(cfg, out.parent / "_state"), log=print)
    print(json.dumps({"title": rep["title"], "qa_ok": rep["qa"]["ok"], "failed": rep["qa"]["failed"], "metrics": rep["qa"]["metrics"],
                      "video": rep["edit"]["video"]}, indent=1))
    return 0 if rep["qa"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
