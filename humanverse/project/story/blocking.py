"""Blocking for "The Kite That Came Home": turns real dialogue durations into frame-accurate scene specs and the
shot-by-shot storyboard. Positions are metres; heading 0 faces the default camera (-Y), 90 faces +X.

Called by `hv storyboard`; it must define block(lines: dict, cast_blends: dict, profile: dict) -> (storyboard, specs).
"""

from __future__ import annotations

import math

FPS = 24


def secs(f):
    return round(f / FPS, 2)


class Timeline:
    def __init__(self, lines):
        self.lines = lines
        self.events = []
        self.cues = []

    def ev(self, char, op, **kw):
        self.events.append({"char": char, "op": op, **kw})

    def say(self, char, line_id, f, **kw):
        ln = self.lines[line_id]
        self.ev(char, "say", line_id=line_id, f=f, **kw)
        return f + int(math.ceil(ln["duration"] * FPS))


def shot(shot_id, scene_id, f0, f1, cam, chars, location, action, emotion, angle, movement, lighting, dialogue, sfx, notes, end=None):
    s = {"shot_id": shot_id, "scene_id": scene_id, "f0": f0, "f1": f1, "cam": cam, "character_ids": chars, "location": location, "action": action,
         "emotion": emotion, "camera_angle": angle, "camera_movement": movement, "lens": f"{cam.get('lens', 40)}mm", "lighting": lighting,
         "duration": secs(f1 - f0 + 1), "dialogue": dialogue, "sound_effects": sfx, "continuity_notes": notes}
    if end:
        s["end"] = end
    return s


A, T, R, I, N = "CHAR-HUM-001", "CHAR-HUM-002", "CHAR-HUM-003", "CHAR-HUM-004", "CHAR-HUM-005"


def scene1(lines):
    t = Timeline(lines)
    walk_end = 12 + int(2.6 / 0.95 * FPS)
    t.ev(A, "walk", f=12, path=[[-3.0, 0.5], [-0.65, 0.0]], heading=55)
    t.ev(A, "expression", f=12, name="excited")
    t.ev(I, "idle", f0=1, f1=walk_end + 200, energy=0.6)
    t.ev(I, "look", f=walk_end - 30, yaw=35, pitch=0)
    t.ev(A, "wave", f0=walk_end + 2, f1=walk_end + 40, side="L")
    e1 = t.say(A, "L01", walk_end + 6, base="excited", gesture=False)
    t.ev(I, "expression", f=e1 + 2, name="happy")
    t.ev(I, "nod", f=e1 + 4)
    e2 = t.say(I, "L02", e1 + 10, base="happy", hand="R")
    rise0, rise1 = e2 - 6, e2 + 60
    t.ev(A, "look", f=rise0 + 10, yaw=10, pitch=30)
    t.ev(I, "look", f=rise0 + 14, yaw=-10, pitch=28)
    t.ev(A, "expression", f=rise0 + 18, name="laughing")
    e3 = t.say(A, "L03", rise1 - 30, base="laughing", gesture=False)
    t.ev(A, "cheer", f0=rise1 - 30, f1=e3 + 10)
    end = e3 + 30
    kite = {"type": "kite", "keys": [{"f": 1, "loc": [0.95, -0.25, 1.05], "rot": [0, 0, 20]}, {"f": rise0, "loc": [0.95, -0.25, 1.1], "rot": [0, 0, 20]},
                                    {"f": rise0 + 24, "loc": [1.6, 2.0, 2.6], "rot": [20, 10, -10]},
                                    {"f": rise1, "loc": [2.4, 5.0, 4.6], "rot": [5, -8, 15]}, {"f": end, "loc": [2.6, 5.2, 4.9], "rot": [5, 10, -12]}]}
    shots = [
        shot("S01_SH01", "S01", 1, walk_end, {"loc": [0.2, -7.2, 1.6], "target": [0, 0.3, 0.9], "lens": 30}, [A, I], "Fernmoor Park",
             "Amara runs in from the left towards Grandpa, who holds the dragon kite", "excited anticipation", "wide, eye level", "static",
             "late-morning sun, warm key from camera right, cool sky fill", [], ["footsteps on grass", "birdsong", "light wind"],
             "Kite in Grandpa's hands; Amara enters frame left"),
        shot("S01_SH02", "S01", walk_end + 1, rise0 + 8, {"loc": [0.1, -3.7, 1.15], "target": [0.1, 0, 0.95], "lens": 36, "focus": [0, 0, 1.0]},
             [A, I], "Fernmoor Park", "Amara waves; Grandpa nods and readies the kite", "joy, warmth", "medium two-shot", "slow push-in",
             "same sun; rim light separates both from the trees", ["L01", "L02"], ["wind gust"], "Amara screen left, Grandpa screen right",
             end={"loc": [0.1, -3.2, 1.12], "target": [0.1, 0, 0.95], "lens": 36}),
        shot("S01_SH03", "S01", rise0 + 9, end, {"loc": [-1.7, -2.6, 0.45], "target": [0.6, 2.5, 2.6], "lens": 26}, [A, I], "Fernmoor Park",
             "The kite climbs; Amara laughs and cheers, both look up", "wonder, delight", "low angle looking up", "slow tilt up",
             "backlit kite against the sky", ["L03"], ["kite flapping", "wind"], "Kite rises screen right to upper frame",
             end={"loc": [-1.7, -2.6, 0.4], "target": [0.9, 3.5, 3.4], "lens": 26}),
    ]
    spec = {"scene_id": "S01", "environment": "park", "seed": 1, "frames": end, "light_center": [0, 0, 0.9],
            "characters": [{"id": A, "start": [-3.0, 0.5, 90], "expression": "happy"}, {"id": I, "start": [0.75, 0.15, -35], "expression": "neutral"}],
            "performance": t.events, "props": [kite], "shots": shots}
    return spec


def scene2(lines):
    t = Timeline(lines)
    t.ev(A, "look", f=6, yaw=15, pitch=32)
    t.ev(A, "expression", f=14, name="surprised")
    t.ev(A, "cry", f0=40, f1=230)
    t.ev(A, "look", f=40, yaw=0, pitch=-5)
    t.ev(A, "slump", f0=40, f1=200)
    e4 = t.say(A, "L04", 46, base="crying", gesture=False)
    walk_f = e4 - 18
    walk_end = walk_f + int(2.8 / 0.95 * FPS)
    t.ev(T, "walk", f=walk_f, path=[[3.4, 0.9], [0.75, 0.1]], heading=-60)
    t.ev(T, "expression", f=walk_f, name="worried")
    e5 = t.say(T, "L05", walk_end + 4, base="worried", hand="R")
    t.ev(T, "reach", f0=e5 - 6, f1=e5 + 40, side="R", fwd=55, raise_=10)
    t.ev(A, "look", f=e5 - 10, yaw=-25, pitch=8)
    t.ev(A, "expression", f=e5 + 4, name="sad")
    t.ev(T, "expression", f=e5 + 2, name="happy")
    e6 = t.say(T, "L06", e5 + 10, base="happy", hand="L")
    t.ev(A, "expression", f=e6 - 4, name="happy")
    t.ev(A, "nod", f=e6 + 2)
    end = e6 + 34
    kite = {"type": "kite", "keys": [{"f": 1, "loc": [2.4, 5.0, 4.6], "rot": [5, -8, 15]}, {"f": 12, "loc": [2.8, 5.6, 4.9], "rot": [10, 20, 30]},
                                    {"f": 60, "loc": [9.0, 14.0, 8.5], "rot": [40, 80, 120]}, {"f": end, "loc": [30, 40, 12], "rot": [40, 80, 160]}]}
    shots = [
        shot("S02_SH01", "S02", 1, e4 + 4, {"loc": [-0.9, -2.5, 0.75], "target": [0.5, 2.0, 1.6], "lens": 30}, [A], "Fernmoor Park",
             "The string snaps; the kite tumbles away; Amara's joy turns to tears", "shock, then grief", "low medium, looking past Amara to the sky",
             "static", "sun goes behind thin cloud: softer, cooler key", ["L04"], ["string snap", "wind gust", "sniffles"],
             "Tears start at frame 40; kite exits upper right"),
        shot("S02_SH02", "S02", e4 + 5, e5, {"loc": [0.1, -5.0, 1.35], "target": [0.1, 0.3, 0.9], "lens": 35}, [A, T], "Fernmoor Park",
             "Teo walks in and stops beside his sister", "concern", "wide two-shot", "static", "soft overcast key",
             ["L05"], ["footsteps on grass"], "Teo enters screen right"),
        shot("S02_SH03", "S02", e5 + 1, end, {"loc": [0.25, -2.9, 1.2], "target": [0.25, 0, 0.95], "lens": 36, "focus": [0.2, 0, 1.0]}, [A, T],
             "Fernmoor Park", "Teo turns it into a plan; Amara wipes the tears and nods", "comfort, hope", "medium two-shot, eye level",
             "slow push-in", "warmth returns: key brightens slightly", ["L06"], ["birdsong returns"], "Tears stop; Amara ends on a small smile",
             end={"loc": [0.25, -2.55, 1.18], "target": [0.25, 0, 0.95], "lens": 36}),
    ]
    spec = {"scene_id": "S02", "environment": "park", "seed": 1, "frames": end, "light_center": [0, 0, 0.9], "key": 0.85,
            "characters": [{"id": A, "start": [-0.3, 0.0, 20], "expression": "laughing"}, {"id": T, "start": [3.4, 0.9, -90], "expression": "neutral"}],
            "performance": t.events, "props": [kite], "shots": shots}
    return spec


def scene3(lines):
    t = Timeline(lines)
    w0 = 10
    arrive = w0 + int(3.0 / 0.85 * FPS)
    t.ev(A, "walk", f=w0, path=[[-3.6, 0.2], [-0.45, 0.0]], heading=40)
    t.ev(T, "walk", f=w0 + 8, path=[[-4.4, 0.7], [-1.25, 0.55]], heading=35)
    t.ev(I, "walk", f=w0 + 4, path=[[-4.6, 0.0], [-2.0, 0.15]], heading=30, speed=0.7)
    t.ev(N, "idle", f0=1, f1=400, energy=0.6)
    t.ev(R, "idle", f0=1, f1=400, energy=0.7)
    t.ev(N, "look", f=arrive - 10, yaw=40, pitch=-6)
    t.ev(R, "look", f=arrive - 6, yaw=45, pitch=0)
    t.ev(N, "expression", f=arrive, name="happy")
    e7 = t.say(N, "L07", arrive + 6, base="happy", hand="L")
    t.ev(A, "expression", f=e7, name="surprised")
    e8 = t.say(A, "L08", e7 + 6, base="surprised", gesture=False)
    t.ev(A, "expression", f=e8, name="excited")
    t.ev(A, "cheer", f0=e8 - 4, f1=e8 + 26)
    e9 = t.say(N, "L09", e8 + 8, base="happy", hand="L")
    t.ev(R, "expression", f=e9 - 6, name="happy")
    e10 = t.say(R, "L10", e9 + 8, base="happy", hand="R")
    t.ev(I, "expression", f=e10 - 4, name="laughing")
    e11 = t.say(I, "L11", e10 + 6, base="laughing", hand="R")
    for c in (A, T, R, N):
        t.ev(c, "expression", f=e11 + 2, name="laughing")
    t.ev(A, "cheer", f0=e11 + 4, f1=e11 + 40)
    t.ev(T, "cheer", f0=e11 + 8, f1=e11 + 42)
    t.ev(N, "wave", f0=e11 + 4, f1=e11 + 40, side="R")
    end = e11 + 50
    kite = {"type": "kite", "keys": [{"f": 1, "loc": [0.55, -0.3, 1.05], "rot": [0, 0, -20]}, {"f": e8 + 2, "loc": [0.55, -0.3, 1.05], "rot": [0, 0, -20]},
                                    {"f": e8 + 20, "loc": [-0.05, -0.3, 1.45], "rot": [-10, 0, 10]}, {"f": e11 + 10, "loc": [-0.75, -0.15, 1.55], "rot": [-10, 0, 10]},
                                    {"f": end, "loc": [-0.8, -0.1, 1.95], "rot": [-15, 0, 0]}]}
    shots = [
        shot("S03_SH01", "S03", 1, arrive + 4, {"loc": [0.0, -8.0, 1.8], "target": [-0.4, 0.5, 1.0], "lens": 30}, [A, T, I, N, R], "Maple Street",
             "The family walks up the street; Noor waits by her gate holding the kite, Rosa beside her", "hope", "wide, eye level",
             "slow truck right", "low golden sunset, long shadows, warm windows", [], ["footsteps on pavement", "evening street hum"],
             "Family enters screen left in age order",
             end={"loc": [0.6, -7.6, 1.8], "target": [-0.2, 0.5, 1.0], "lens": 30}),
        shot("S03_SH02", "S03", arrive + 5, e7, {"loc": [0.9, -2.2, 1.35], "target": [0.6, 0.1, 1.25], "lens": 50, "focus": [0.75, 0.1, 1.3]}, [N, R],
             "Maple Street", "Noor offers the kite", "playful", "medium over the family's shoulder", "static", "sunset rim on hair", ["L07"],
             [], "Kite in Noor's hands"),
        shot("S03_SH03", "S03", e7 + 1, e8 + 20, {"loc": [-0.25, -1.45, 1.0], "target": [-0.45, 0, 0.98], "lens": 55, "focus": [-0.45, 0, 1.0]}, [A],
             "Maple Street", "Amara's surprise becomes joy", "surprise to delight", "close-up", "static", "warm key on face, catchlights",
             ["L08"], ["small gasp"], "Amara frames left of centre"),
        shot("S03_SH04", "S03", e8 + 21, end, {"loc": [0.0, -4.6, 1.45], "target": [-0.2, 0.3, 1.0], "lens": 34}, [A, T, I, N, R], "Maple Street",
             "Everyone laughs; Grandpa invites Noor for tomorrow; Amara holds the kite up", "shared joy", "wide group shot", "slow pull-back",
             "sunset key, warm practical windows", ["L09", "L10", "L11"], ["laughter", "cheer"], "All five in frame; kite ends above Amara",
             end={"loc": [0.0, -5.4, 1.55], "target": [-0.2, 0.3, 1.05], "lens": 34}),
    ]
    spec = {"scene_id": "S03", "environment": "street", "seed": 3, "frames": end, "light_center": [-0.6, 0.2, 0.95], "key": 0.9,
            "characters": [{"id": A, "start": [-3.6, 0.2, 90], "expression": "happy"}, {"id": T, "start": [-4.4, 0.7, 90], "expression": "happy"},
                           {"id": I, "start": [-4.6, 0.0, 90], "expression": "happy"}, {"id": N, "start": [0.95, 0.2, -35], "expression": "neutral"},
                           {"id": R, "start": [1.75, 0.65, -40], "expression": "neutral"}],
            "performance": t.events, "props": [kite], "shots": shots}
    return spec


def block(lines: dict, cast_blends: dict, profile: dict):
    specs = [scene1(lines), scene2(lines), scene3(lines)]
    for s in specs:
        s["fps"] = FPS
        s["resolution"] = profile["resolution"]
        s["samples"] = profile["samples"]
        for c in s["characters"]:
            c["blend"] = cast_blends[c["id"]]
    shots = [{k: v for k, v in sh.items() if k not in ("cam", "end", "f0", "f1")} | {"frames": [sh["f0"], sh["f1"]]}
             for s in specs for sh in s["shots"]]
    for sh in shots:
        sh["dialogue"] = [{"line_id": lid, "character_id": lines[lid]["character_id"], "text": lines[lid]["text"]} for lid in sh["dialogue"]]
    storyboard = {"title": "The Kite That Came Home", "fps": FPS, "scene_ids": [s["scene_id"] for s in specs], "shots": shots,
                  "approved": False, "total_seconds": round(sum(s["frames"] for s in specs) / FPS, 2)}
    return storyboard, specs
