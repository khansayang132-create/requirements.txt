"""Foley spotting: sound events timecoded from the animation itself.

Nothing here guesses from the script. The stage's ``Renderer.pose`` is pure and cheap, so we
sample it for every actor at every video frame of every shot (the same function that draws the
picture) and listen to what the puppet does:

  footsteps     a foot comes back down (the rig lifts a foot while sin(step + side*pi) > 0):
                walk-ins, dance steps, tiptoes; the exact contact time is refined by bisection
                on the continuous pose between the two frames
  take-off      ``lift`` leaves 0 (a jump starts)                          -> small cloth swish
  landing       ``lift`` returns to 0, or reaches the bottom of a hop cycle -> thump on the surface
  claps         the arms of a clapping actor reach their closest point     -> clap
  arm swishes   a fast arm stroke (>= 30 degrees) on waves, points, gives, stretches, dances, and
                a hard pose change on a cut                                -> cloth swish
  settles       an actor sits into sleep / hug / sleepy                    -> soft settle
  strokes       brushing and washing strokes                               -> brush / wash
  props         pop-ins at their cue times (the stage's ``appear_scale`` rule), falling leaves
                touching the ground, give (whoosh out) and receive (gentle catch), sparkle fx
  splashes      landings in the rain get a small splash

Surfaces follow the environment (grass outside, wood floors, bathroom tile, wet ground in the rain).
Every event carries time, frame, timecode HH:MM:SS:FF, shot, source, layer, gain and pan
(pan from the actor's x on screen; the mixer keeps it moderate). A density cap keeps busy shots
gentle: simultaneous identical hits from several actors are merged, and no one-second window
holds more than ``MAX_PER_SECOND`` events (the least important are dropped first).
"""

from __future__ import annotations

import math
import zlib

from ..render.stage import Renderer, Shot, _phase, show_layout

SURFACE = {"meadow": "grass", "garden": "grass", "pond": "grass", "hilltop": "grass", "forest": "grass", "night": "grass",
           "rainy": "water", "playroom": "wood", "bedroom": "wood", "bathroom": "tile"}
MAX_PER_SECOND = 6            # all layers together, any 1-second window
MAX_SFX_PER_SHOT = 2          # hard effects per shot (the storyboard's rule); storyboard cues win over added ones
MIN_JUMP = 30.0               # pixels of lift that count as a real jump (walk bounce is 12, clap bounce 8)
MERGE_WINDOW = 0.05           # identical hits closer than this are one hit
# importance when the density cap has to drop something (higher survives)
PRIORITY = {"sfx": 10, "landing": 8, "pop_in": 8, "catch": 7, "give": 7, "clap": 6, "settle": 6, "splash": 6, "sparkle": 6,
            "footstep": 5, "tiptoe": 4, "wash": 4, "takeoff": 3, "swish": 3, "brush": 3, "leaf": 2}
GAIN = {"footstep": 0.10, "dance_step": 0.06, "tiptoe": 0.045, "landing": 0.17, "takeoff": 0.045, "clap": 0.085, "swish": 0.06,
        "settle": 0.08, "brush": 0.035, "wash": 0.05, "pop_in": 0.11, "leaf": 0.035, "give": 0.06, "catch": 0.08, "splash": 0.09}
SWISH_ACTIONS = {"wave", "point", "give", "receive", "hold_up", "stretch", "yawn", "dance", "look_up", "wow"}
SETTLE_ACTIONS = {"sleep", "hug", "sleepy"}
# cyclic actions repeat the same hit all shot long: keep the first three, then every second one, softer
PERIODIC = {"landing", "clap", "brush", "wash", "swish", "footstep", "tiptoe", "takeoff"}


def timecode(t: float, fps: int) -> str:
    f = int(round(t * fps))
    s, ff = divmod(f, fps)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{ff:02d}"


def _pan(x: float) -> float:
    return max(-1.0, min(1.0, (x - 540.0) / 540.0))


def _bisect(fn, a: float, b: float, it: int = 22) -> float:
    """First time in (a, b] where fn(t) becomes True (fn(a) False, fn(b) True)."""
    for _ in range(it):
        m = (a + b) / 2
        if fn(m):
            b = m
        else:
            a = m
    return b


def _argmin(fn, a: float, b: float, it: int = 40) -> float:
    for _ in range(it):
        m1, m2 = a + (b - a) / 3, b - (b - a) / 3
        if fn(m1) <= fn(m2):
            b = m2
        else:
            a = m1
    return (a + b) / 2


class Spotter:
    """Spots the Foley of one episode. ``spot()`` returns (events, stats)."""

    def __init__(self, shots: list[Shot], universe: dict | None, fps: int = 24):
        self.shots, self.fps = shots, fps
        self.r = Renderer(universe or {"characters": []}, 1080, 1920, fps)
        self.events: list[dict] = []
        self.starts = []
        t = 0.0
        for s in shots:
            self.starts.append(t)
            t += s.duration
        self.total = t

    # -------------------------------------------------------------------- helpers --
    def _ev(self, si: int, t: float, kind: str, sound: str, source: str, x: float, layer: str = "foley", gain: float | None = None,
            actor: str | None = None, **kw):
        shot = self.shots[si]
        if t < 0 or t >= shot.duration:
            return
        T = self.starts[si] + t
        e = {"t": round(T, 4), "frame": int(math.floor(T * self.fps + 1e-6)), "timecode": timecode(T, self.fps), "shot": si,
             "shot_t": round(t, 4), "layer": layer, "kind": kind, "source": source, "env": shot.env,
             "gain": round(GAIN.get(kind, 0.06) if gain is None else gain, 4), "pan": round(_pan(x), 3)}
        if actor:
            e["actor"] = actor
        if layer == "foley":
            e["sound"] = sound
            e["surface"] = SURFACE.get(shot.env, "grass")
            e["variant"] = zlib.crc32(f"{source}:{T:.3f}".encode()) % 3
        else:
            e["name"] = sound
        e.update(kw)
        self.events.append(e)

    def _pose(self, a, si: int, t: float):
        return self.r.pose(a, self.shots[si], t, self.starts[si] + t, 0.0)

    # -------------------------------------------------------------------- actors ---
    def _actor(self, si: int, a, prev_pose) -> None:
        shot, fps = self.shots[si], self.fps
        n = max(1, round(shot.duration * fps))
        ts = [f / fps for f in range(n)]
        P = [self._pose(a, si, t) for t in ts]
        src = f"{a.id}:{a.action}"
        lift = [p.lift for p in P]

        # footsteps: a foot is up while sin(step + phase) > 0 (characters.draw_character)
        if any(p.step for p in P):
            walking = a.enter == "walk"
            kind = "footstep" if walking else ("tiptoe" if a.action == "tiptoe" else "footstep")
            gain = GAIN["footstep"] if walking else (GAIN["tiptoe"] if a.action == "tiptoe" else GAIN["dance_step"])
            steps: list[tuple[float, str]] = []
            for side, ph in (("left", 0.0), ("right", math.pi)):
                def up(t, ph=ph):
                    return math.sin(self._pose(a, si, t).step + ph) > 1e-9
                for f in range(1, n):
                    if up(ts[f - 1]) and not up(ts[f]):
                        steps.append((_bisect(lambda t: not up(t), ts[f - 1], ts[f]), side))
            kept: list[float] = []
            for tc, side in sorted(steps):
                if kept and tc - kept[-1] < 0.12:
                    continue                              # the rig resets the step phase when a walk-in ends
                kept.append(tc)
                what = "walk-in" if walking and tc < 0.95 else a.action
                self._ev(si, tc, kind, "footstep", f"{a.id} {side} foot down ({what})", self._pose(a, si, tc).x, gain=gain, actor=a.id)

        # jumps: take-off when lift leaves 0, landing when it returns to 0 or bottoms out in a hop cycle
        eps = 0.5
        last_mark, peak = 0.0, lift[0]
        for f in range(1, n):
            peak = max(peak, lift[f])
            landed = None
            if lift[f - 1] > eps and lift[f] <= eps:
                landed = _bisect(lambda t: self._pose(a, si, t).lift <= eps, ts[f - 1], ts[f])
            elif f < n - 1 and lift[f] > eps and lift[f] <= lift[f - 1] and lift[f] < lift[f + 1] and lift[f] < 0.2 * peak:
                landed = _argmin(lambda t: self._pose(a, si, t).lift, ts[f - 1], ts[f + 1])
            elif lift[f - 1] <= eps and lift[f] > eps:
                tk = _bisect(lambda t: self._pose(a, si, t).lift > eps, ts[f - 1], ts[f])
                hi = max(lift[f:f + int(0.5 * fps)] or [0])
                if hi >= MIN_JUMP and tk - last_mark > 0.15:
                    self._ev(si, tk, "takeoff", "swish", f"{a.id} take-off ({a.action})", P[f].x, actor=a.id)
                last_mark, peak = tk, lift[f]
                continue
            if landed is not None:
                if peak >= MIN_JUMP:
                    g = GAIN["landing"] * max(0.35, min(1.0, peak / 140.0))
                    what = "hop-in" if a.enter == "hop" and landed <= 0.61 else a.action
                    self._ev(si, landed, "landing", "thump", f"{a.id} lands ({what}, lift {peak:.0f}px -> 0)", P[f].x, gain=round(g, 4),
                             lift_peak=round(peak, 1), actor=a.id)
                    if shot.env == "rainy":
                        self._ev(si, landed + 0.01, "splash", "splash", f"{a.id} lands in a puddle", P[f].x, layer="sfx",
                                 gain=GAIN["splash"])
                last_mark, peak = landed, lift[f]

        # arm strokes: extrema of each arm's angle (not while the entrance animation owns the arms)
        busy = 0.95 if a.enter == "walk" else (0.6 if a.enter == "hop" else 0.0)
        for side, key in (("left", "arm_l"), ("right", "arm_r")):
            ang = [getattr(p, key) for p in P]
            ext = [0] + [f for f in range(1, n - 1) if (ang[f] - ang[f - 1]) * (ang[f + 1] - ang[f]) < 0 and ts[f] > busy] + [n - 1]
            if a.action == "clap" and side == "left":
                for f in ext[1:-1]:
                    if ang[f] < ang[f - 1]:          # minimum = hands together
                        tc = _argmin(lambda t: self._pose(a, si, t).arm_l, ts[f - 1], ts[f + 1])
                        self._ev(si, tc, "clap", "clap", f"{a.id} claps (hands meet)", P[f].x, actor=a.id)
            elif a.action == "brush" and side == "right":
                for f in ext[1:-1]:
                    if ang[f] > ang[f - 1]:
                        self._ev(si, ts[f], "brush", "brush", f"{a.id} brushing stroke", P[f].x, actor=a.id)
            elif a.action == "wash" and side == "left":
                for f in ext[1:-1]:
                    if ang[f] > ang[f - 1]:
                        self._ev(si, ts[f], "wash", "wash", f"{a.id} washing stroke", P[f].x, actor=a.id)
            elif a.action in SWISH_ACTIONS:
                last = -9.0
                for f0, f1 in zip(ext, ext[1:]):
                    d = ang[f1] - ang[f0]
                    if abs(d) < 30 or f1 - f0 < 1:
                        continue
                    fm = max(range(f0 + 1, f1 + 1), key=lambda k: abs(ang[k] - ang[k - 1]))
                    if ts[fm] - last < 0.6 or (a.enter == "walk" and ts[fm] < 0.95):
                        continue
                    last = ts[fm]
                    self._ev(si, ts[fm], "swish", "swish", f"{a.id} {side} arm stroke {d:+.0f} deg ({a.action})", P[fm].x,
                             gain=round(GAIN["swish"] * min(1.0, abs(d) / 90), 4), actor=a.id)

        # hard pose change on a cut (same place, same actor, arm jumps)
        if prev_pose is not None and not a.enter:
            jump = max(abs(P[0].arm_l - prev_pose.arm_l), abs(P[0].arm_r - prev_pose.arm_r))
            if jump >= 40:
                self._ev(si, 0.04, "swish", "swish", f"{a.id} pose change on the cut (arm {jump:.0f} deg)", P[0].x,
                         gain=round(GAIN["swish"] * min(1.0, jump / 90), 4))
        if a.action in SETTLE_ACTIONS and (prev_pose is None or prev_pose.mood != P[0].mood or a.enter):
            t0 = 0.97 if a.enter == "walk" else (0.62 if a.enter == "hop" else 0.12)
            self._ev(si, t0, "settle", "settle", f"{a.id} settles ({a.action})", self._pose(a, si, t0).x, actor=a.id)

    # -------------------------------------------------------------------- props ----
    def _props(self, si: int) -> None:
        shot = self.shots[si]
        units = [(it, i) for it in shot.items if it.layout == "show" for i in range(it.count)]
        slots = show_layout(len(units))
        for idx, ((it, i), (sx, _, _)) in enumerate(zip(units, slots)):
            if it.appear != "already":
                t0 = it.cue[i] if it.cue and i < len(it.cue) else 0.25 + 0.3 * idx
                self._ev(si, t0, "pop_in", "pop_in", f"prop pops in: {it.name} #{i + 1}", sx)
        for it in shot.items:
            if it.appear == "already":
                continue
            if it.layout == "ground":
                size, x0 = it.size or 70, it.x if it.x is not None else 540
                for i in range(it.count):
                    t0 = it.cue[i] if it.cue and i < len(it.cue) else 0.25 + 0.3 * i
                    self._ev(si, t0, "pop_in", "pop_in", f"prop pops in: {it.name} #{i + 1} (ground)", x0 + (i - (it.count - 1) / 2) * size * 1.7)
            elif it.layout == "sky":
                t0 = it.cue[0] if it.cue else 0.25
                self._ev(si, t0, "pop_in", "pop_in", f"prop pops in: {it.name} (sky)", it.x or 540)
        T0, T1 = self.starts[si], self.starts[si] + shot.duration
        for it in shot.items:
            if it.layout != "fall":
                continue
            for i in range(it.count):                     # stage._falling: y = 180 + ((tg*150 + ph*300) % 1250), hidden past 1300
                ph = _phase(f"{it.name}{i}")
                m = math.ceil((T0 * 150 + ph * 300 - 1120) / 1250)
                while True:
                    tg = (1120 - ph * 300 + 1250 * m) / 150
                    if tg >= T1:
                        break
                    if tg >= T0:
                        x = 80 + (ph * 157.0) % (1080 - 160) + 30 * math.sin(tg * 1.3 + ph)
                        self._ev(si, tg - T0, "leaf", "pat", f"falling {it.name} #{i + 1} touches the ground", x)
                    m += 1
        tr = shot.transfer
        if tr:
            byid = {a.id: a for a in shot.actors}
            fx_ = byid[tr["from"]].x if tr.get("from") in byid else 540
            tx_ = byid[tr["to"]].x if tr.get("to") in byid else 540
            self._ev(si, float(tr.get("start", 0.5)), "give", "give", f"{tr.get('from')} gives the {tr['name']}", fx_)
            self._ev(si, float(tr.get("end", 1.5)), "catch", "catch", f"{tr.get('to')} receives the {tr['name']}", tx_)

    def _sfx(self, si: int) -> None:
        shot = self.shots[si]
        has_pop = any(e["shot"] == si and e["kind"] == "pop_in" for e in self.events)
        names = []
        for e in shot.sfx:
            if e["name"] == "pop" and has_pop and float(e.get("at", 0.2)) == 0.25:
                continue                                  # the generic storyboard pop is replaced by timecoded pop-ins
            names.append(e["name"])
            self._ev(si, float(e.get("at", 0.2)), "sfx", e["name"], f"storyboard cue: {e['name']}", 540, layer="sfx", gain=None)
        if shot.fx == "sparkle" and "sparkle" not in names:
            self._ev(si, 0.35, "sparkle", "sparkle", "sparkle fx on screen", 540, layer="sfx")

    # -------------------------------------------------------------------- run ------
    def spot(self) -> tuple[list[dict], dict]:
        last_pose: dict[str, object] = {}
        prev_env = None
        for si, shot in enumerate(self.shots):
            cur = {}
            for a in shot.actors:
                self._actor(si, a, last_pose.get(a.id) if shot.env == prev_env else None)
                cur[a.id] = self._pose(a, si, max(0.0, shot.duration - 1 / self.fps))
            last_pose, prev_env = cur, shot.env
            self._props(si)
            self._sfx(si)
        for e in self.events:
            if e["layer"] == "sfx" and e["gain"] is None:
                e.pop("gain")
        raw = len(self.events)
        self.events = cap_sfx(self.events, MAX_SFX_PER_SHOT)
        self.events = thin(self.events)
        thinned = raw - len(self.events)
        ev = merge(sorted(self.events, key=lambda e: e["t"]))
        merged = raw - thinned - len(ev)
        ev, dropped = cap_density(ev, MAX_PER_SECOND)
        return ev, {"detected": raw, "thinned_repeats": thinned, "merged": merged, "dropped_by_density_cap": dropped, "kept": len(ev),
                    "max_per_second": MAX_PER_SECOND}


def cap_sfx(events: list[dict], cap: int) -> list[dict]:
    """At most ``cap`` hard effects per shot: storyboard cues first, then the earliest added ones."""
    keep, count = [], {}
    for e in sorted(events, key=lambda e: (e["layer"] != "sfx", e["kind"] != "sfx", e["t"])):
        if e["layer"] == "sfx":
            if count.get(e["shot"], 0) >= cap:
                continue
            count[e["shot"]] = count.get(e["shot"], 0) + 1
        keep.append(e)
    return sorted(keep, key=lambda e: e["t"])


def thin(events: list[dict]) -> list[dict]:
    """Cyclic actions (a cheer, a clap, a hop) repeat the same hit for the whole shot. Keep the first three
    of each actor's cycle, then every second one, each a little softer (never below 60 %)."""
    groups: dict = {}
    for e in sorted(events, key=lambda e: e["t"]):
        if e.get("actor") and e["kind"] in PERIODIC and "walk-in" not in e["source"]:
            groups.setdefault((e["shot"], e["actor"], e["kind"]), []).append(e)
    drop = set()
    for g in groups.values():
        for i, e in enumerate(g):
            if i >= 3 and i % 2:
                drop.add(id(e))
            elif i:
                e["gain"] = round(e["gain"] * max(0.6, 0.88 ** i), 4)
    return [e for e in events if id(e) not in drop]


def merge(events: list[dict]) -> list[dict]:
    """Identical hits within MERGE_WINDOW (e.g. three friends landing together) become one, a bit louder."""
    out: list[dict] = []
    for e in events:
        key = e.get("sound", e.get("name"))
        twin = next((o for o in reversed(out[-6:]) if o.get("sound", o.get("name")) == key and o["layer"] == e["layer"]
                     and e["t"] - o["t"] <= MERGE_WINDOW), None)
        if twin is None:
            out.append(dict(e))
            continue
        n = twin.get("merged", 1) + 1
        twin["pan"] = round((twin["pan"] * (n - 1) + e["pan"]) / n, 3)
        if "gain" in twin and "gain" in e:              # several bodies: a little fuller, never a pile-up
            twin["_gmax"] = max(twin.get("_gmax", twin["gain"]), e["gain"])
            twin["gain"] = round(twin["_gmax"] * min(1.4, 1 + 0.2 * (n - 1)), 4)
        twin["source"] += " + " + e["source"]
        twin["merged"] = n
    for o in out:
        o.pop("_gmax", None)
    return out


def cap_density(events: list[dict], cap: int) -> tuple[list[dict], int]:
    """Drop the least important events until no 1-second window holds more than ``cap``."""
    ev = sorted(events, key=lambda e: e["t"])
    dropped = 0
    while True:
        worst = None
        j = 0
        for i in range(len(ev)):
            while ev[i]["t"] - ev[j]["t"] >= 1.0:
                j += 1
            if i - j + 1 > cap:
                worst = (j, i)
                break
        if worst is None:
            return ev, dropped
        j, i = worst
        k = min(range(j, i + 1), key=lambda q: (PRIORITY.get(ev[q]["kind"], 1), ev[q].get("gain", 1)))
        ev.pop(k)
        dropped += 1


def spot(shots: list[Shot], universe: dict | None, fps: int = 24) -> tuple[list[dict], dict]:
    return Spotter(shots, universe, fps).spot()


def density(events: list[dict], duration: float) -> dict:
    ts = sorted(e["t"] for e in events)
    mx, j = 0, 0
    for i in range(len(ts)):
        while ts[i] - ts[j] >= 1.0:
            j += 1
        mx = max(mx, i - j + 1)
    return {"events": len(ts), "per_second_mean": round(len(ts) / max(duration, 1e-6), 3), "per_second_max": mx}
