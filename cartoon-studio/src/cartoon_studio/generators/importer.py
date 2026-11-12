"""Bring a v0.3 universe (text-only `universe.json` + `characters.json`) into the V3 production format.

The owner's files are read, never rewritten: the V3 bible goes to `universes/<id>/universe-bible.json`, and each
character's original `character.json` stays byte-for-byte as it was (its sha256 is locked into `bible.json`).

The local engine draws five body plans (bunny, cat, elephant, duck, bear). A species it has no model for is drawn
with the closest free body plan, and that choice is written down in `visual.engine_body` and `source.engine_note`,
so nobody mistakes the stand-in for the real design. A true turtle or moth needs a custom model or an image provider.
"""

from __future__ import annotations

import colorsys
import hashlib
import json
from pathlib import Path

from ..engine import ACCESSORIES, ENVIRONMENTS, SPECIES
from ..state import AnimationDesign, CharacterSpec, Identity, UniverseBible, VisualDesign
from .originality import check_name
from .universe import ESPEAK, KOKORO, RUN, WALK

# keyword in the owner's species -> engine body plan, in order of preference
HINTS = [("rabbit", "bunny"), ("bunny", "bunny"), ("hare", "bunny"), ("fox", "cat"), ("cat", "cat"), ("badger", "bear"),
         ("bear", "bear"), ("moth", "duck"), ("bird", "duck"), ("duck", "duck"), ("owl", "duck"), ("turtle", "elephant"),
         ("tortoise", "elephant"), ("elephant", "elephant")]
PLACE_HINTS = [("clearing", "meadow"), ("field", "meadow"), ("meadow", "meadow"), ("creek", "pond"), ("pond", "pond"), ("river", "pond"),
               ("garden", "garden"), ("panorama", "hilltop"), ("hill", "hilltop"), ("forest", "forest"), ("wood", "forest")]


def _shade(hex_color: str, light: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, _light, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, light)), s)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def pick_bodies(species: list[str]) -> list[str]:
    free, out = list(SPECIES), []
    for sp in species:
        body = next((b for k, b in HINTS if k in sp.lower() and b in free), None) or free[0]
        free.remove(body)
        out.append(body)
    return out


def _place(name: str, used: set[str]) -> str:
    env = next((e for k, e in PLACE_HINTS if k in name.lower() and e not in used), None)
    return env or next(e for e in ENVIRONMENTS if e not in used and e not in ("bathroom", "bedroom", "playroom"))


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def import_legacy(root: Path, uid: str, extra_places: dict[str, str] | None = None) -> UniverseBible:
    d = root / "universes" / uid
    meta = json.loads((d / "universe.json").read_text(encoding="utf-8"))
    raw = json.loads((d / "characters.json").read_text(encoding="utf-8"))
    bodies = pick_bodies([c["species"] for c in raw])
    accessories = list(ACCESSORIES)
    chars: list[CharacterSpec] = []
    for i, (c, body) in enumerate(zip(raw, bodies)):
        src = root / "character-bibles" / c["id"] / "character.json"
        primary = c["palette"]["primary"]
        colors = {"body": primary, "belly": c["palette"].get("secondary", "#F2E6C8"), "inner_ear": _shade(primary, 0.85),
                  "accent": c["palette"].get("accent", "#6B8F58"), "nose": _shade(primary, 0.35)}
        acc = accessories[i % len(accessories)]
        vd, ad = c.get("visual_design", {}), c.get("animation_design", {})
        note = "" if body in c["species"].lower() else f"drawn with the engine's {body} body: it has no {c['species']} model"
        chars.append(CharacterSpec(
            character_id=c["id"], name=c["name"], role="lead" if i == 0 else "friend",
            identity=Identity(species=c["species"], age_category=c.get("age_category", "child"), personality=c.get("personality", []),
                              background=c.get("backstory", ""), strengths=c.get("strengths", []), weaknesses=c.get("weaknesses", []),
                              emotions="shows feelings openly", catchphrase=""),
            visual=VisualDesign(face=vd.get("face", ""), eyes="large readable eyes", proportions=vd.get("body", ""), surface=vd.get("surface", ""),
                                clothing=f"{acc} in accent colour {colors['accent']}", accessory=acc, palette=colors,
                                distinctive=vd.get("distinctive_feature", ""), engine_body=body),
            animation=AnimationDesign(walk=WALK[body], run=RUN[body], talk=ad.get("talk", ""), expressions=["happy", "wow", "sad", "thinking"],
                                      reactions="small gasp when surprised", idle=ad.get("idle", ""), signature_moves=[ad.get("signature", "wave")]),
            voice={"kokoro": {"voice": KOKORO[i % len(KOKORO)], "speed": 0.92, "pitch": 1.0},
                   "espeak": {"voice": ESPEAK[i % len(ESPEAK)], "rate": 135 + 3 * i, "pitch": 40 + 9 * i},
                   "elevenlabs": {"voice_id": "", "stability": 0.5}},
            source={"format": "cartoon-studio v0.3", "character_json": str(src.relative_to(root)) if src.is_file() else None,
                    "character_json_sha256": sha256_file(src) if src.is_file() else None,
                    "v0_3_reference_hash": c.get("reference_hash"), "engine_note": note},
        ))
    for a in chars:
        a.relationships = {o.character_id: "friend" for o in chars if o is not a}
    places: dict[str, str] = {}
    for name in (extra_places or {}):
        places[_place(name, set(places))] = name
    issues = [f"{c.name}: {p}" for c in chars for p in check_name(c.name)]
    return UniverseBible(
        universe_id=uid, title=meta["title"], concept=meta.get("premise", ""), world=meta.get("premise", ""), tone=meta.get("tone", ""),
        audience="ages 4-8", world_rules=meta.get("world_rules", []), places=places, recurring_storylines=[], episode_concepts=[],
        characters=chars,
        originality={"source": "owner's v0.3 universe", "note": meta.get("originality_note", ""), "issues": [],
                     "warnings": issues + [f"{c.name}: {c.source['engine_note']}" for c in chars if c.source["engine_note"]]})
