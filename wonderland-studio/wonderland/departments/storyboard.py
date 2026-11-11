"""Storyboard department: story beats → stage shots.

Decides the things a director decides: where each character stands, who walks in,
who faces whom, which sound effect marks which moment, and how long each shot holds.
The output is plain data (``Shot`` dataclasses) that the animation department renders
and the audio department scores; nothing here draws or synthesizes.
"""

from __future__ import annotations

from dataclasses import asdict

from ..render.stage import Actor, Item, Overlay, Shot

SLOTS = {1: [540.0], 2: [315.0, 765.0], 3: [215.0, 540.0, 865.0]}
SCALE = {1: 0.95, 2: 0.86, 3: 0.74}
MAX_SFX_PER_SHOT = 2           # gentle sound design: never a wall of effects


def build_shots(story: dict) -> list[Shot]:
    shots: list[Shot] = []
    prev_ids: list[str] = []
    prev_env = None
    prev_x: dict[str, float] = {}
    for bi, beat in enumerate(story["beats"]):
        ids = [a["id"] for a in beat["actors"]][:3]
        n = max(1, len(ids))
        xs = SLOTS[n]
        env_changed = beat["env"] != prev_env
        actors = []
        sfx: list[dict] = []
        for i, a in enumerate(beat["actors"][:3]):
            x = xs[i]
            facing = 1 if x <= 540 else -1
            if n == 1:
                facing = 1
            enter = None
            if bi == 0:
                enter = "hop" if i == 0 else "walk"
            elif a["id"] not in prev_ids and not env_changed:
                enter = "walk"
            hold = a.get("hold")
            if hold and hold.get("name") is None:
                hold = None
            action = a.get("action", "idle")
            actors.append(Actor(id=a["id"], x=x, action=action, facing=facing, enter=enter, scale=SCALE[n], hold=hold))
            if enter == "walk":
                sfx.append({"name": "whoosh", "at": 0.05})
            if enter == "hop":
                sfx.append({"name": "boing", "at": 0.05})
        items = []
        new_show = 0
        for it in beat["items"]:
            d = {k: v for k, v in it.items() if k in Item.__dataclass_fields__}
            items.append(Item(**d))
            if it.get("appear") == "pop" and it.get("layout") in ("show", "ground", "sky"):
                new_show += 1
        if new_show and not any(s == "tick" for s in beat.get("sfx", [])):
            sfx.append({"name": "pop", "at": 0.25})
        for name in beat.get("sfx", []):
            sfx.append({"name": name, "at": 0.3})
        if beat.get("fx") == "sparkle":
            sfx.append({"name": "sparkle", "at": 0.35})
        seen, trimmed = set(), []
        for s in sfx:
            if s["name"] not in seen:
                trimmed.append(s)
                seen.add(s["name"])
        ov = beat.get("overlay")
        overlay = Overlay(text=ov["text"], style=ov.get("style", "word"), color=ov.get("color", "red"), sub=ov.get("sub")) if ov else None
        transfer = dict(beat["transfer"]) if beat.get("transfer") else None
        if transfer:
            transfer.setdefault("start", 0.5)
            transfer.setdefault("end", 1.5)
        shots.append(Shot(env=beat["env"], actors=actors, items=items, overlay=overlay, caption=beat["text"], speaker=beat["speaker"],
                          transfer=transfer, fx=beat.get("fx"), sfx=trimmed[:MAX_SFX_PER_SHOT]))
        prev_ids, prev_env = ids, beat["env"]
        prev_x = {a.id: a.x for a in actors}
    del prev_x
    return shots


def time_shots(shots: list[Shot], voices: list[dict], fps: int, mood: str, min_total: float, max_total: float,
               bar_seconds: float | None = None) -> dict:
    """Give every shot its duration from its recorded line. Returns a timing report.

    Each shot = lead-in + line + tail, rounded to whole frames. Bedtime ("calm") episodes
    breathe more. Rhymes are placed on the bar grid of their tune. If the total is under
    ``min_total`` the pauses are stretched a little; over ``max_total`` they are tightened.
    """
    lead_in = {"calm": 0.45}.get(mood, 0.28)
    tail = {"calm": 0.85, "song": 0.3}.get(mood, 0.5)
    durs = []
    for shot, v in zip(shots, voices):
        start = lead_in + (0.7 if any(a.enter == "walk" for a in shot.actors) else 0.0) + (0.35 if any(a.enter == "hop" for a in shot.actors) else 0.0)
        d = start + v["duration"] + tail
        if shot.transfer:
            d = max(d, 2.2)
        d = max(d, 1.5)
        if bar_seconds:
            half = bar_seconds / 2
            import math

            d = math.ceil((d - 0.05) / half) * half
        durs.append([start, d])
    total = sum(d for _, d in durs)
    stretch = 0.0
    if total < min_total:
        stretch = min(0.9, (min_total - total) / len(durs) + 0.02)
    elif total > max_total:
        stretch = -min(tail - 0.12, (total - max_total) / len(durs) + 0.02)
    t = 0.0
    for shot, v, (start, d) in zip(shots, voices, durs):
        d = d + stretch
        frames = max(1, round(d * fps))
        shot.duration = frames / fps
        v["start"] = start
        v["shot_start"] = t
        t += shot.duration
    return {"total_seconds": round(t, 3), "shots": len(shots), "stretch_per_shot": round(stretch, 3), "lead_in": lead_in, "tail": tail,
            "on_bar_grid": bool(bar_seconds)}


def shots_to_json(shots: list[Shot]) -> list[dict]:
    out = []
    for s in shots:
        d = asdict(s)
        if d.get("voice"):
            d["voice"]["envelope"] = f"<{len(d['voice']['envelope'])} frames>"
        out.append(d)
    return out
