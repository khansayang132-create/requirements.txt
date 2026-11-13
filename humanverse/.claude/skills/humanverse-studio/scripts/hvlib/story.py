"""Screenplay and storyboard contracts. A storyboard that misses a field cannot reach rendering."""

from __future__ import annotations

SCREENPLAY_FIELDS = ("title", "logline", "audience", "genre", "theme", "motivations", "conflict", "emotional_progression", "scenes", "ending")
SCENE_FIELDS = ("scene_id", "heading", "purpose", "location", "characters", "lines")
SHOT_FIELDS = ("shot_id", "scene_id", "character_ids", "location", "action", "emotion", "camera_angle", "camera_movement", "lens",
               "lighting", "duration", "dialogue", "sound_effects", "continuity_notes")


def validate_screenplay(sp: dict, cast_ids: set[str]) -> list[str]:
    errs = [f"screenplay missing {k}" for k in SCREENPLAY_FIELDS if not sp.get(k)]
    seen = set()
    for sc in sp.get("scenes", []):
        errs += [f"{sc.get('scene_id')}: missing {k}" for k in SCENE_FIELDS if k not in sc]
        if not str(sc.get("purpose", "")).strip():
            errs.append(f"{sc.get('scene_id')}: a scene needs a narrative purpose")
        for c in sc.get("characters", []):
            if c not in cast_ids:
                errs.append(f"{sc['scene_id']}: unknown character {c}")
        for ln in sc.get("lines", []):
            if ln["line_id"] in seen:
                errs.append(f"duplicate line id {ln['line_id']}")
            seen.add(ln["line_id"])
            if ln["character_id"] not in cast_ids:
                errs.append(f"{ln['line_id']}: unknown speaker {ln['character_id']}")
            if len(ln["text"].split()) > 16:
                errs.append(f"{ln['line_id']}: line longer than 16 words")
    return errs


def validate_storyboard(sb: dict) -> list[str]:
    errs = []
    if not sb.get("approved"):
        errs.append("storyboard not approved (director must approve before final rendering)")
    scenes_with_shots = {}
    for sh in sb.get("shots", []):
        miss = [k for k in SHOT_FIELDS if sh.get(k) in (None, "", [])
                and k not in ("dialogue", "sound_effects")]
        errs += [f"{sh.get('shot_id')}: missing {m}" for m in miss]
        if sh.get("duration", 0) <= 0:
            errs.append(f"{sh.get('shot_id')}: non-positive duration")
        scenes_with_shots.setdefault(sh.get("scene_id"), 0)
        scenes_with_shots[sh.get("scene_id")] += 1
    for sid in sb.get("scene_ids", []):
        if not scenes_with_shots.get(sid):
            errs.append(f"{sid}: no shots")
    return errs
