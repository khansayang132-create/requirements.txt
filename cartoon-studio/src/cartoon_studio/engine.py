"""Bridge to the in-house animation engine (wonderland-studio): 2D/3D toon renderer, voices, Foley, mix and QC.

It is the studio's free, local, deterministic production path: no API key, no credits. The engine renders five body
plans (bunny, cat, elephant, duck, bear) with five signature accessories; every new universe builds its own characters
on those rigs (new names, colours, outfits, personalities, voices, movement).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WONDERLAND_ROOT") or Path(__file__).resolve().parents[3] / "wonderland-studio")
SPECIES = ("bunny", "cat", "elephant", "duck", "bear")
ACCESSORIES = ("scarf", "bow", "bandana", "boots", "overalls")
ENVIRONMENTS = ("meadow", "garden", "pond", "hilltop", "forest", "rainy", "playroom", "bathroom", "bedroom", "night")
ACTIONS = ("idle", "hop", "wave", "cheer", "dance", "point", "look_up", "nod", "think", "sad", "sleep", "yawn", "sleepy", "give",
           "receive", "clap", "brush", "wash", "stretch", "wow", "hug", "tiptoe", "hold_up")


def available() -> tuple[bool, str]:
    if not (ROOT / "wonderland" / "pipeline.py").is_file():
        return False, f"engine not found at {ROOT} (set WONDERLAND_ROOT)"
    return True, str(ROOT)


def load():
    """Import the engine package (adds its folder to sys.path once)."""
    ok, why = available()
    if not ok:
        from .errors import ProviderNotConfigured

        raise ProviderNotConfigured("local-engine", why)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import wonderland  # noqa: F401

    return ROOT
