"""The stage: turns a list of ``Shot`` objects into video frames.

A shot is one spoken line: who is on stage, what they do, which props are visible,
the big overlay word and the caption. The storyboard department writes shots; this
module only draws them. Timing comes from the voice track (each shot lasts as long as
its line plus padding) and mouths follow the loudness of the recorded line, so picture
and sound cannot drift apart.

Layout (1080x1920 design space, scaled for other output sizes):
  y ~ 250   overlay word / number / title
  y 430-720 showcase props
  y = 1340  the ground line the characters stand on
  y ~ 1540  caption box (kept left of the Shorts button column and above the title area)
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from .canvas import Canvas, Grade, clamp, darken, ease_in_out, ease_out, ease_out_back, font, hex_rgb, lighten
from .characters import Pose, draw_character, hand_pos, head_top
from .environments import ENVS, GROUND_Y, H, W, background, background_plate
from .props import COLORS, draw_prop, heart_points, star_points

INK = (59, 51, 85)
CREAM = (255, 246, 227)
CAPTION_CX, CAPTION_Y, CAPTION_MAXW = 500, 1540, 800

@dataclass
class Actor:
    id: str
    x: float
    action: str = "idle"
    mood: str = "happy"
    facing: int = 1               # 1 faces right, -1 faces left
    enter: str | None = None      # walk | hop | None (already on stage)
    scale: float = 0.9
    hold: dict | None = None      # {"name", "color", "side", "size"}

@dataclass
class Item:
    name: str
    color: str | None = None
    count: int = 1
    layout: str = "show"          # show | ground | sky | fall | fly
    appear: str = "pop"           # pop | already
    cue: list[float] | None = None
    x: float | None = None
    y: float | None = None
    size: float | None = None
    highlight: bool = False
    label: str | None = None      # text drawn on the item (e.g. a letter on a block)
    front: bool = False

@dataclass
class Overlay:
    text: str
    style: str = "word"           # word | number | letter | title | end
    color: str = "#F2545B"
    sub: str | None = None

@dataclass
class Voice:
    path: str
    start: float                  # seconds into the shot where the line begins
    duration: float
    envelope: list[float] = field(default_factory=list)   # loudness 0..1 per video frame

@dataclass
class Shot:
    env: str
    actors: list[Actor] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    overlay: Overlay | None = None
    caption: str = ""
    speaker: str = "narrator"
    duration: float = 3.0
    voice: Voice | None = None
    transfer: dict | None = None  # {"name","color","from","to","start","end","size"}
    fx: str | None = None         # sparkle | hearts | notes | zzz
    sfx: list[dict] = field(default_factory=list)   # [{"name","at"}] consumed by the audio department

def _phase(key: str) -> float:
    return int(hashlib.md5(key.encode()).hexdigest()[:6], 16) / 0xFFFFFF * 6.283

def show_layout(n: int) -> list[tuple[float, float, float]]:
    """Positions (x, y, size) for n showcase props."""
    if n <= 0:
        return []
    if n == 1:
        return [(540, 620, 136)]
    if n <= 5:
        size = {2: 128, 3: 108, 4: 92, 5: 78}[n]
        span = {2: 360, 3: 600, 4: 700, 5: 760}[n]
        return [(540 - span / 2 + span * i / (n - 1), 630, size) for i in range(n)]
    top = (n + 1) // 2
    out = []
    for row, cnt in ((0, top), (1, n - top)):
        span = 190 * (cnt - 1)
        for i in range(cnt):
            out.append((540 - span / 2 + 190 * i, 520 + row * 190, 70))
    return out

def wrap_text(text: str, size: int, max_w: float, weight: int = 600) -> list[str]:
    f = font(size, weight)
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if f.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

class Renderer:
    def __init__(self, universe: dict, width: int = 1080, height: int = 1920, fps: int = 24, grade: bool = True):
        if abs(width / height - W / H) > 0.01:
            raise ValueError("output must be 9:16")
        self.specs = {c["id"]: c for c in universe["characters"]}
        self.width, self.height, self.fps = width, height, fps
        self.k = 2
        self.ss = self.k * width / W           # internal pixels per design pixel
        self.os = width / W                    # output pixels per design pixel
        self.grade = Grade(width, height) if grade else None
        self.three = None                      # a three_backend.Session: characters come from the 3D renderer
        self._anchors: dict | None = None

    # ------------------------------------------------------------------ 3D layer -----
    def facing_side(self, a: Actor, shot: Shot, t: float, tg: float) -> float:
        """-1 (faces left) .. +1 (faces right), eased over ~0.25 s when ``Pose.flip`` changes, so the
        3D character turns instead of snapping. Uses only the pure ``pose`` function (deterministic)."""
        acc = wsum = 0.0
        for i in range(7):
            ti = max(0.0, t - i * 0.04)
            w = 1.0 - i / 7
            acc += w * (-1.0 if self.pose(a, shot, ti, tg - (t - ti), 0.0).flip else 1.0)
            wsum += w
        return acc / wsum

    def three_records(self, shot: Shot, t: float, tg: float, poses: dict[str, Pose]) -> list[dict]:
        from .three_backend import pose_record

        out = []
        for a in shot.actors:
            side = self.facing_side(a, shot, t, tg)
            walking = clamp((0.95 - t) / 0.2) if a.enter == "walk" else 0.0
            out.append(pose_record(a.id, poses[a.id], side, side * (26 + 26 * walking)))
        return out

    def character_layer(self, shot: Shot, t: float, tg: float, poses: dict[str, Pose] | None = None):
        """Render this frame's characters with the 3D backend (``self.three`` must be a Session)."""
        self.submit_layer(shot, t, tg, poses)
        return self.three.collect()

    def submit_layer(self, shot: Shot, t: float, tg: float, poses: dict[str, Pose] | None = None) -> None:
        """Start the 3D render of a frame (collect with ``self.three.collect()``)."""
        from .three_backend import light_preset

        if poses is None:
            poses = self.poses(shot, t, tg)
        self.three.set_lights(shot.env, light_preset(shot.env))
        self.three.submit(self.three_records(shot, t, tg, poses))

    def poses(self, shot: Shot, t: float, tg: float) -> dict[str, Pose]:
        talk = self.talk(shot, t)
        return {a.id: self.pose(a, shot, t, tg, talk if a.id == shot.speaker else 0.0) for a in shot.actors}

    def talk(self, shot: Shot, t: float) -> float:
        fi = int(t * self.fps)
        if shot.voice and shot.voice.envelope:
            j = fi - int(shot.voice.start * self.fps)
            if 0 <= j < len(shot.voice.envelope):
                return shot.voice.envelope[j]
        return 0.0

    def _paste_layer(self, c: Canvas, layer) -> None:
        """Composite a premultiplied RGBA layer (output pixels) onto the supersampled canvas."""
        if layer is None or layer.rgba is None:
            return
        from PIL import ImageChops

        x0, y0, w, h = layer.box
        k = c.ss / self.os
        im = Image.frombuffer("RGBa", (w, h), layer.rgba.tobytes(), "raw", "RGBa", 0, 1)   # premultiplied
        if abs(k - 1) > 1e-6:
            im = im.resize((round(w * k), round(h * k)), Image.BILINEAR)
        X0, Y0 = round(x0 * k), round(y0 * k)
        r, g, b, a = im.split()
        region = c.img.crop((X0, Y0, X0 + im.width, Y0 + im.height))
        inv = ImageChops.invert(a)
        out = ImageChops.add(ImageChops.multiply(region, Image.merge("RGB", (inv, inv, inv))), Image.merge("RGB", (r, g, b)))
        c.img.paste(out, (X0, Y0))

    def _hand(self, aid: str, p: Pose, side: int) -> tuple[float, float]:
        if self._anchors and aid in self._anchors:
            return self._anchors[aid]["hand_r" if side > 0 else "hand_l"]
        return hand_pos(p, side)

    def _head_top(self, aid: str, p: Pose) -> tuple[float, float]:
        if self._anchors and aid in self._anchors:
            return self._anchors[aid]["head_top"]
        return head_top(p)

    # ------------------------------------------------------------------ poses -------
    def pose(self, a: Actor, shot: Shot, t: float, tg: float, talking: float) -> Pose:
        ph = _phase(a.id)
        p = Pose(x=a.x, y=GROUND_Y, scale=a.scale, flip=a.facing < 0, mood=a.mood)
        p.squash = 0.014 * math.sin(tg * 2.4 + ph)
        blink_t = (tg + ph) % 3.4
        p.blink = 1.0 if blink_t < 0.13 else 0.0
        p.ear = 3.0 * math.sin(tg * 1.3 + ph)
        p.mouth = talking
        if talking > 0.05:
            p.head_tilt = 2.0 * math.sin(tg * 5.0 + ph)

        act = a.action
        if a.enter == "walk" and t < 0.95:
            k = ease_out(t / 0.95)
            start = -220 if a.x < 540 else W + 220
            p.x = start + (a.x - start) * k
            p.step = t * 15
            p.lift = abs(math.sin(t * 15)) * 12 * (1 - k)
            p.flip = a.x > 540 if k < 0.9 else p.flip
            p.arm_l, p.arm_r = 30 + 18 * math.sin(t * 15), 30 - 18 * math.sin(t * 15)
            return p
        if a.enter == "hop" and t < 0.6:
            k = t / 0.6
            p.lift = 260 * (1 - k) ** 2 + 4 * 70 * k * (1 - k)
            p.squash = -0.1 * (1 - k)
            p.arm_l = p.arm_r = 120
            return p

        if act == "hop":
            T = 0.72
            k = (t % T) / T
            p.lift = 4 * 84 * k * (1 - k)
            p.squash = 0.12 if (k < 0.1 or k > 0.92) else -0.07 * math.sin(k * math.pi)
            p.arm_l = p.arm_r = 70 + 50 * math.sin(k * math.pi)
        elif act == "wave":
            p.arm_r = 138 + 22 * math.sin(t * 9)
            p.head_tilt += 4
        elif act == "cheer":
            T = 0.8
            k = (t % T) / T
            p.lift = 4 * 46 * k * (1 - k)
            p.arm_l = 150 + 12 * math.sin(t * 10)
            p.arm_r = 150 - 12 * math.sin(t * 10)
            p.mouth = max(p.mouth, 0.45)
        elif act == "dance":
            p.lean = 6 * math.sin(t * 4.2)
            p.lift = abs(math.sin(t * 4.2)) * 20
            p.arm_l = 95 + 45 * math.sin(t * 4.2)
            p.arm_r = 95 - 45 * math.sin(t * 4.2)
            p.step = t * 8.4
        elif act == "point":
            side_right = a.x <= 540
            if side_right != (a.facing < 0):
                p.arm_r = 152 + 5 * math.sin(t * 3)
            else:
                p.arm_l = 152 + 5 * math.sin(t * 3)
            p.look_y = -0.9
            p.look = 0.5 if a.x < 540 else (-0.5 if a.x > 540 else 0)
        elif act == "look_up":
            p.look_y = -1.0
            p.mood = "wow"
            p.head_tilt = -3
        elif act == "nod":
            p.head_tilt = 6 * math.sin(t * 7)
        elif act == "think":
            p.head_tilt = -8
            p.look, p.look_y = -0.6, -0.8
            p.ear = 10 * math.sin(t * 6)
        elif act == "sad":
            p.mood = "sad"
            p.head_tilt = 7
            p.arm_l = p.arm_r = 8
            p.look_y = 0.6
        elif act == "sleep":
            p.mood = "asleep"
            p.head_tilt = 9
            p.squash = 0.03 * math.sin(tg * 1.4)
            p.arm_l = p.arm_r = 10
            p.mouth = 0
        elif act == "yawn":
            k = clamp((t - 0.3) / max(0.8, shot.duration - 0.8))
            p.mood = "sleepy"
            p.mouth = max(p.mouth, math.sin(k * math.pi) ** 0.6 * 0.95)
            p.arm_l = 30 + 125 * math.sin(k * math.pi)
            p.arm_r = 30 + 125 * math.sin(k * math.pi)
            p.squash = -0.05 * math.sin(k * math.pi)
        elif act == "sleepy":
            p.mood = "sleepy"
            p.head_tilt = 5 * math.sin(tg * 1.1)
        elif act == "give":
            if a.facing > 0:
                p.arm_r = 86
            else:
                p.arm_l = 86
            p.look = 0.7 * a.facing
        elif act == "receive":
            p.arm_l = p.arm_r = 80
            p.mood = "wow"
        elif act == "clap":
            p.arm_l = 62 + 26 * math.sin(t * 14)
            p.arm_r = 62 + 26 * math.sin(t * 14)
            p.lift = abs(math.sin(t * 7)) * 8
        elif act == "brush":
            p.arm_r = 146 + 7 * math.sin(t * 16)
            p.mouth = max(p.mouth, 0.32)
        elif act == "wash":
            p.arm_l = 58 + 9 * math.sin(t * 13)
            p.arm_r = 58 - 9 * math.sin(t * 13)
            p.look_y = 0.7
        elif act == "stretch":
            k = math.sin(clamp(t / max(0.6, shot.duration)) * math.pi)
            p.arm_l = p.arm_r = 30 + 130 * k
            p.squash = -0.06 * k
        elif act == "wow":
            p.mood = "wow"
            p.arm_l = p.arm_r = 60
        elif act == "hug":
            p.lean = 5 * a.facing
            p.arm_l = p.arm_r = 78
            p.blink = 1.0
        elif act == "tiptoe":
            p.step = t * 6
            p.lift = 4
        elif act == "hold_up":
            if (a.hold or {}).get("side", 1) > 0:
                p.arm_r = 150
            else:
                p.arm_l = 150
        if a.hold and act not in ("hold_up", "brush", "give"):
            if a.hold.get("side", 1) > 0:
                p.arm_r = max(p.arm_r, 74)
            else:
                p.arm_l = max(p.arm_l, 74)
        return p

    # ------------------------------------------------------------------ frame -------
    def frame(self, shot: Shot, t: float, tg: float, layer=None) -> Image.Image:
        """One video frame. ``layer`` (a ``three_backend.Layer``) replaces the 2D characters with a
        pre-rendered RGBA character layer; when it is None and ``self.three`` is set, it is rendered here."""
        env = ENVS[shot.env]
        plate = background_plate(shot.env, self.ss) if self.grade else background(shot.env, self.ss)
        c = Canvas(W, H, self.ss, base=plate, k=self.k)
        if env.ambient:
            env.ambient(c, tg)

        poses = self.poses(shot, t, tg)
        if layer is None and self.three is not None and shot.actors:
            layer = self.character_layer(shot, t, tg, poses)
        self._anchors = layer.anchors if layer is not None else None

        # --- props: sky + ground (behind actors) + showcase
        units = []
        for it in shot.items:
            if it.layout == "show":
                units.extend((it, i) for i in range(it.count))
        slots = show_layout(len(units))
        labels: list[tuple[str, float, float, float]] = []

        def appear_scale(it: Item, i: int, idx: int) -> float:
            if it.appear == "already":
                return 1.0
            t0 = it.cue[i] if it.cue and i < len(it.cue) else 0.25 + 0.3 * idx
            if t < t0:
                return 0.0
            return ease_out_back((t - t0) / 0.38)

        for it in shot.items:
            if it.layout == "sky":
                s = appear_scale(it, 0, 0)
                if s > 0:
                    draw_prop(c, it.name, it.x or 540, (it.y or 520) + math.sin(tg * 0.9) * 6, (it.size or 150) * s, it.color, tg)
            elif it.layout == "ground" and not it.front:
                self._ground_item(c, it, t, tg, appear_scale, labels)
            elif it.layout == "fall":
                self._falling(c, it, tg)
            elif it.layout == "fly":
                for i in range(it.count):
                    fx = (it.x or 540) + 230 * math.sin(tg * 0.6 + i * 2.2)
                    fy = (it.y or 700) + 90 * math.sin(tg * 1.1 + i * 1.3)
                    draw_prop(c, it.name, fx, fy, it.size or 60, it.color, tg + i, rot=10 * math.sin(tg * 2 + i))

        for idx, ((it, i), (sx, sy, size)) in enumerate(zip(units, slots)):
            s = appear_scale(it, i, idx)
            if s <= 0:
                continue
            bob = math.sin(tg * 1.5 + idx * 0.9) * (9 if it.name in ("balloon", "butterfly", "kite", "cloud", "bubbles", "firefly") else 4)
            pulse = 1 + (0.07 * math.sin(tg * 5.5) if it.highlight else 0)
            draw_prop(c, it.name, sx, sy + bob, (it.size or size) * s * pulse, it.color, tg + idx)
            if it.label:
                labels.append((it.label, sx, sy + bob, (it.size or size) * s))

        # --- actors (2D puppets, or the 3D layer pasted at the same depth)
        if layer is not None:
            self._paste_layer(c, layer)
        for a in shot.actors:
            p = poses[a.id]
            if layer is None:
                draw_character(c, self.specs[a.id], p, shadow_color=env.shadow)
            if a.hold and not self._receiving(shot, a, t):
                self._held(c, a, p, tg)

        for it in shot.items:
            if it.layout == "ground" and it.front:
                self._ground_item(c, it, t, tg, appear_scale, labels)

        if shot.transfer:
            self._transfer(c, shot.transfer, poses, t, tg)
        if shot.fx:
            self._fx(c, shot, poses, t, tg)

        cap_box = self._caption_layout(shot)
        if cap_box:
            x0, y0, x1, y1 = cap_box["box"]
            c.rrect(x0, y0 + 8, x1, y1 + 8, 44, darken(env.shadow, 0.1))
            c.rrect(x0, y0, x1, y1, 44, CREAM, INK, 5)
            if cap_box.get("tag"):
                tx0, ty0, tx1, ty1 = cap_box["tag_box"]
                c.rrect(tx0, ty0, tx1, ty1, 26, cap_box["tag_color"], INK, 5)

        img = c.finish()
        if self.grade:
            img = self.grade.apply(img, dark=env.dark, keep=cap_box)
        d = ImageDraw.Draw(img)
        os_ = self.os
        for text, lx, ly, size in labels:
            d.text((lx * os_, ly * os_), text, font=font(max(8, round(size * 0.9 * os_)), 700), fill=(255, 255, 255),
                   anchor="mm", stroke_width=max(1, round(4 * os_)), stroke_fill=INK)
        if shot.overlay:
            self._overlay(d, shot.overlay, t, env.dark)
        if shot.fx == "zzz":
            self._zzz(d, shot, poses, tg)
        if cap_box:
            fsize = round(cap_box["size"] * os_)
            for i, line in enumerate(cap_box["lines"]):
                d.text((CAPTION_CX * os_, (cap_box["text_y"] + i * cap_box["lh"]) * os_), line, font=font(fsize, 600),
                       fill=INK, anchor="mm")
            if cap_box.get("tag"):
                tx0, ty0, tx1, ty1 = cap_box["tag_box"]
                d.text(((tx0 + tx1) / 2 * os_, (ty0 + ty1) / 2 * os_), cap_box["tag"], font=font(round(38 * os_), 700),
                       fill=(255, 255, 255), anchor="mm", stroke_width=max(1, round(2 * os_)), stroke_fill=INK)
        return img

    # ---------------------------------------------------------------- helpers -------
    def _ground_item(self, c, it: Item, t, tg, appear_scale, labels) -> None:
        n = it.count
        size = it.size or 70
        x0 = it.x if it.x is not None else 540
        for i in range(n):
            s = appear_scale(it, i, i)
            if s <= 0:
                continue
            x = x0 + (i - (n - 1) / 2) * size * 1.7
            y = (it.y if it.y is not None else GROUND_Y + 14) - size * 0.86 * s
            draw_prop(c, it.name, x, y, size * s, it.color, tg + i)
            if it.label:
                labels.append((it.label, x, y, size * s))

    def _falling(self, c, it: Item, tg) -> None:
        for i in range(it.count):
            ph = _phase(f"{it.name}{i}")
            x = 80 + (ph * 157.0) % (W - 160) + 30 * math.sin(tg * 1.3 + ph)
            y = 180 + ((tg * 150 + ph * 300) % 1250)
            if y < GROUND_Y - 40:
                draw_prop(c, it.name, x, y, it.size or 34, it.color, tg, rot=40 * math.sin(tg * 1.7 + ph))

    @staticmethod
    def _receiving(shot: Shot, a: Actor, t: float) -> bool:
        """The receiver of a hand-off already holds the prop in the story data; it is drawn in their hand only once it
        has arrived, so the prop is never on screen twice (found in ep004/ep006: a second kite during the hand-off)."""
        tr = shot.transfer
        return bool(tr and tr.get("to") == a.id and (a.hold or {}).get("name") == tr["name"] and t < tr.get("end", 1.6))

    @staticmethod
    def _lift(name: str, size: float) -> float:
        """How far above the hand a prop is drawn: kites and balloons float on their string."""
        return size * (1.72 if name in ("balloon", "kite") else 0.9 if name == "umbrella" else 0.35)

    def _held(self, c, a: Actor, p: Pose, tg) -> None:
        h = a.hold
        side = h.get("side", 1)
        hx, hy = self._hand(a.id, p, side)   # side +1 = the arm_r hand (the one the pose raises)
        size = h.get("size", 58)
        if h["name"] in ("balloon", "kite"):
            draw_prop(c, h["name"], hx, hy - size * 1.72, size, h.get("color"), tg)
        elif h["name"] == "toothbrush":
            draw_prop(c, h["name"], hx - 34 * (1 if side > 0 else -1), hy - 26, size, h.get("color"), tg, flip=side < 0)
        elif h["name"] == "umbrella":
            draw_prop(c, h["name"], hx, hy - size * 0.9, size, h.get("color"), tg)
        else:
            draw_prop(c, h["name"], hx, hy - size * 0.35, size, h.get("color"), tg)

    def _transfer(self, c, tr: dict, poses: dict[str, Pose], t, tg) -> None:
        a, b = poses.get(tr["from"]), poses.get(tr["to"])
        if not a or not b:
            return
        ax, ay = self._hand(tr["from"], a, 1 if b.x > a.x else -1)
        bx, by = self._hand(tr["to"], b, -1 if b.x > a.x else 1)
        if t >= tr.get("end", 1.6):
            return                                    # arrived: the receiver's held prop takes over
        k = ease_in_out((t - tr.get("start", 0.5)) / max(0.1, tr.get("end", 1.6) - tr.get("start", 0.5)))
        x = ax + (bx - ax) * k
        y = ay + (by - ay) * k - 26 * math.sin(k * math.pi)
        size = tr.get("size", 56)
        draw_prop(c, tr["name"], x, y - self._lift(tr["name"], size), size, tr.get("color"), tg)

    def _fx(self, c, shot: Shot, poses, t, tg) -> None:
        if shot.fx == "sparkle":
            for i in range(9):
                ph = i * 0.7
                k = ((tg * 0.6 + ph) % 1.0)
                x = 150 + (i * 97) % 800 + 20 * math.sin(tg + i)
                y = 980 - k * 420
                r = 20 * math.sin(k * math.pi)
                if r > 2:
                    c.shape(star_points(x, y, r, r * 0.42, 4, tg * 40 + i * 20), hex_rgb("#FFD95A"), (255, 255, 255), 3)
        elif shot.fx == "hearts":
            for i in range(6):
                k = ((tg * 0.45 + i * 0.17) % 1.0)
                x = 330 + i * 84 + 18 * math.sin(tg * 2 + i)
                y = 1000 - k * 360
                r = 30 * math.sin(k * math.pi)
                if r > 3:
                    c.shape(heart_points(x, y, r), hex_rgb("#FF8FAB"), (255, 255, 255), 3)
        elif shot.fx == "notes":
            cols = ["#FF8FAB", "#4D9DE0", "#FFD43B", "#51CF66", "#9B7EDE"]
            for i in range(7):
                k = ((tg * 0.4 + i * 0.143) % 1.0)
                x = 120 + (i * 143) % 840 + 26 * math.sin(tg * 1.6 + i)
                y = 1020 - k * 520
                s = 0.6 + 0.6 * math.sin(k * math.pi)
                col = hex_rgb(cols[i % len(cols)])
                c.ellipse(x, y, 17 * s, 13 * s, col, darken(col, 0.35), 3)
                c.line([(x + 15 * s, y), (x + 15 * s, y - 52 * s), (x + 36 * s, y - 40 * s)], darken(col, 0.35), 6 * s)

    def _zzz(self, d: ImageDraw.ImageDraw, shot: Shot, poses, tg) -> None:
        os_ = self.os
        for a in shot.actors:
            if a.action != "sleep":
                continue
            hx, hy = self._head_top(a.id, poses[a.id])
            for i in range(3):
                k = ((tg * 0.35 + i * 0.33) % 1.0)
                size = round((46 + 60 * k) * os_)
                x = (hx + 150 + 110 * k + 12 * math.sin(tg * 2 + i)) * os_
                y = (hy + 90 - 230 * k) * os_
                d.text((x, y), "z", font=font(size, 700), fill=lighten("#C9B8FF", 0.3 * (1 - k)), anchor="mm",
                       stroke_width=max(1, round(3 * os_)), stroke_fill=INK)

    def _overlay(self, d: ImageDraw.ImageDraw, ov: Overlay, t: float, dark: bool) -> None:
        os_ = self.os
        pop = ease_out_back(t / 0.4) if t < 0.4 else 1.0
        if pop <= 0.02:
            return
        base = {"word": 180, "number": 230, "letter": 230, "title": 96, "end": 92}.get(ov.style, 170)
        lines = [ov.text]
        if ov.style in ("title", "end"):
            lines = wrap_text(ov.text, base, 900, 700)
            while len(lines) > 3 and base > 60:
                base -= 8
                lines = wrap_text(ov.text, base, 900, 700)
        else:
            while font(base, 700).getlength(ov.text) > 940 and base > 80:
                base -= 10
        size = max(10, int(round(base * pop * os_ / 2)) * 2)
        f = font(size, 700)
        col = hex_rgb(COLORS.get(ov.color, ov.color))
        y = {"word": 320, "number": 300, "letter": 300, "title": 320, "end": 320}.get(ov.style, 320)
        plain = ov.style in ("title", "end")   # white on ink: readable on every background
        lh = base * 1.08
        y0 = y - (len(lines) - 1) * lh / 2
        for i, line in enumerate(lines):
            pos = (540 * os_, (y0 + i * lh) * os_)
            if plain:
                d.text(pos, line, font=f, fill=(255, 255, 255), anchor="mm", stroke_width=max(2, round(base * 0.11 * os_)), stroke_fill=INK)
                continue
            d.text(pos, line, font=f, fill=INK, anchor="mm", stroke_width=max(2, round(base * 0.105 * os_)), stroke_fill=INK)
            d.text(pos, line, font=f, fill=col, anchor="mm", stroke_width=max(1, round(base * 0.06 * os_)), stroke_fill=(255, 255, 255))
        if ov.sub:
            ssz = max(10, round(64 * pop * os_))
            pos = (540 * os_, (y0 + len(lines) * lh - lh * 0.5 + 62) * os_)
            d.text(pos, ov.sub, font=font(ssz, 600), fill=(255, 255, 255) if dark else INK, anchor="mm",
                   stroke_width=max(1, round(5 * os_)), stroke_fill=INK if dark else (255, 255, 255))

    def _caption_layout(self, shot: Shot) -> dict | None:
        text = shot.caption.strip()
        if not text:
            return None
        size = 56
        lines = wrap_text(text, size, CAPTION_MAXW)
        while len(lines) > 3 and size > 40:
            size -= 4
            lines = wrap_text(text, size, CAPTION_MAXW)
        lh = size * 1.22
        widest = max(font(size, 600).getlength(ln) for ln in lines)
        bw = max(260, widest + 90)
        bh = lh * len(lines) + 54
        x0, x1 = CAPTION_CX - bw / 2, CAPTION_CX + bw / 2
        y0, y1 = CAPTION_Y - bh / 2, CAPTION_Y + bh / 2
        out = {"box": (x0, y0, x1, y1), "lines": lines, "size": size, "lh": lh, "text_y": CAPTION_Y - (len(lines) - 1) * lh / 2}
        spec = self.specs.get(shot.speaker)
        if spec:
            name = spec["name"]
            tw = font(38, 700).getlength(name) + 52
            out["tag"] = name
            out["tag_color"] = hex_rgb(spec["colors"]["body"])
            out["tag_box"] = (x0 + 26, y0 - 36, x0 + 26 + tw, y0 + 18)
        return out

def crossfade(a: Image.Image, b: Image.Image, k: float) -> Image.Image:
    return Image.blend(a, b, clamp(k))
