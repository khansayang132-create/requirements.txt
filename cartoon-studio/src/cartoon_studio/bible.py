"""Character bibles: identity JSON + the six reference images, rendered by the local engine, with sha256 locks.

    character-bibles/<id>/character.json      canonical identity (written once; never overwritten, so an owner's file stays as it is)
    character-bibles/<id>/bible.json          full V3 spec + reference_sha256 for every image + sha256 of character.json
    reference_front.png / _side.png / _back.png   cut from the 7-angle 3D turnaround (turnaround.png kept too)
    expression_sheet.png                       moods (happy, talking, wow, blink, sleepy, sad)
    pose_sheet.png                             signature actions (wave, hop, cheer, point, think, hug)
    color_reference.png                        palette swatches with hex codes
    voice_id.txt                               voice profiles per provider

The pipeline refuses to make an episode if a bible is missing or any image no longer matches its recorded hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

from . import engine
from .errors import ConsistencyError
from .state import CharacterSpec, UniverseBible, write_json

FILES = ("reference_front.png", "reference_side.png", "reference_back.png", "expression_sheet.png", "pose_sheet.png", "color_reference.png")
POSES = ("wave", "hop", "cheer", "point", "think", "hug")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _poses(uni: dict, cid: str, out: Path) -> Path:
    from wonderland.render.stage import Actor, Renderer, Shot

    r = Renderer(uni, 540, 960, 24, grade=False)
    tiles = []
    for a in POSES:
        shot = Shot(env="meadow", actors=[Actor(id=cid, x=540, action=a, scale=0.95)], items=[], overlay=None, caption="", speaker="", duration=2.0)
        tiles.append(r.frame(shot, 0.9, 0.9).crop((70, 250, 470, 760)).resize((300, 382)))
    sheet = Image.new("RGB", (300 * 3, 382 * 2 + 40), (255, 246, 227))
    d = ImageDraw.Draw(sheet)
    for i, (t, a) in enumerate(zip(tiles, POSES)):
        x, y = 300 * (i % 3), 382 * (i // 3)
        sheet.paste(t, (x, y))
        d.text((x + 10, y + 10), a, fill=(59, 51, 85))
    sheet.save(out)
    return out


def _colors(c: CharacterSpec, out: Path) -> Path:
    img = Image.new("RGB", (900, 260), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, (k, v) in enumerate(c.visual.palette.items()):
        d.rectangle((20 + 176 * i, 20, 176 * i + 176, 190), fill=v, outline=(59, 51, 85), width=2)
        d.text((24 + 176 * i, 200), f"{k}\n{v}", fill=(59, 51, 85))
    img.save(out)
    return out


def render_bible(u: UniverseBible, c: CharacterSpec, root: Path, backend: str = "auto") -> dict[str, str]:
    engine.load()
    from wonderland.departments.animation import RenderError, character_sheet, character_turnaround

    from .generators.universe import engine_universe

    uni = engine_universe(u)
    one = {**uni, "characters": [ch for ch in uni["characters"] if ch["id"] == c.character_id]}
    d = root / "character-bibles" / c.character_id
    d.mkdir(parents=True, exist_ok=True)
    made_with = "three"
    try:
        if backend == "flat":
            raise RenderError("flat requested")
        turn = character_turnaround(uni, c.character_id, d / "turnaround.png")
        sheet = Image.open(turn)
        k = sheet.width / (240 * 7)
        for name, col in (("reference_front.png", 0), ("reference_side.png", 2), ("reference_back.png", 3)):
            sheet.crop((round(240 * col * k), round(90 * k), round(240 * (col + 1) * k), round(540 * k))).save(d / name)
    except RenderError:
        made_with = "flat"
        _flat_angles(one, c.character_id, d)
    character_sheet(one, d / "expression_sheet.png", backend=made_with if made_with == "three" else "flat")
    _poses(one, c.character_id, d / "pose_sheet.png")
    _colors(c, d / "color_reference.png")
    (d / "voice_id.txt").write_text(json.dumps(c.voice, indent=2), encoding="utf-8")
    hashes = {f: sha256(d / f) for f in FILES}
    c.reference_sha256 = hashes
    if not (d / "character.json").is_file():
        write_json(d / "character.json", {**c.model_dump(exclude={"reference_sha256"}), "universe_id": u.universe_id})
    write_json(d / "bible.json", {**c.model_dump(), "universe_id": u.universe_id, "rendered_with": made_with,
                                  "character_json_sha256": sha256(d / "character.json")})
    return hashes


def _flat_angles(uni: dict, cid: str, d: Path) -> None:
    """2D fallback: the flat rig has front views only; side/back are the same front view, flipped/marked."""
    from wonderland.render.stage import Actor, Renderer, Shot

    r = Renderer(uni, 540, 960, 24, grade=False)
    for name, facing in (("reference_front.png", 1), ("reference_side.png", -1), ("reference_back.png", 1)):
        shot = Shot(env="meadow", actors=[Actor(id=cid, x=540, action="idle", facing=facing, scale=0.95)], items=[], overlay=None,
                    caption="", speaker="", duration=2.0)
        r.frame(shot, 0.5, 0.5).crop((70, 250, 470, 760)).save(d / name)


def verify(root: Path, character_id: str, expected: dict[str, str] | None = None) -> dict[str, str]:
    """Raise ConsistencyError unless the bible exists and every image matches its recorded (and expected) hash."""
    d = root / "character-bibles" / character_id
    if not (d / "bible.json").is_file() or not (d / "character.json").is_file():
        raise ConsistencyError(f"no character bible for {character_id}: run init-characters first")
    meta = json.loads((d / "bible.json").read_text(encoding="utf-8"))
    if meta.get("character_json_sha256") != sha256(d / "character.json"):
        raise ConsistencyError(f"{character_id}: character.json changed since the bible was approved")
    recorded = meta.get("reference_sha256") or {}
    for f in FILES:
        p = d / f
        if not p.is_file():
            raise ConsistencyError(f"{character_id}: {f} is missing")
        if sha256(p) != recorded.get(f):
            raise ConsistencyError(f"{character_id}: {f} changed since the bible was approved")
        if expected and expected.get(f) and expected[f] != recorded.get(f):
            raise ConsistencyError(f"{character_id}: {f} differs from the hash locked into this job")
    return recorded
