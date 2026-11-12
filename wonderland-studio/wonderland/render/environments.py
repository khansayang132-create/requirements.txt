"""The ten Wonder Meadow locations.

Each environment has a static background (built once per render at supersampled size
and cached) and an optional ``ambient`` layer drawn every frame (drifting clouds,
twinkling stars, rain). Ambient motion is slow on purpose: these videos are for
2-5 year olds and must not be overstimulating.

Layout contract shared with the stage (1080x1920 output):
  overlay word  y ~ 250      showcase props  y ~ 430-720
  characters stand on GROUND_Y = 1340          captions  y ~ 1540
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from PIL import Image

from .canvas import Canvas, Xf, darken, hex_rgb, lighten, mix, vertical_gradient
from .props import draw_prop, star_points

W, H = 1080, 1920
GROUND_Y = 1340
HORIZON = 1130


@dataclass(frozen=True)
class Env:
    key: str
    build: Callable[[Canvas], None]
    sky: tuple
    shadow: tuple
    ambient: Callable[[Canvas, float], None] | None = None
    dark: bool = False            # night scenes: light text, calmer music
    indoor: bool = False


def _hills(c: Canvas, far, near) -> None:
    c.ellipse(220, HORIZON + 150, 620, 260, far)
    c.ellipse(900, HORIZON + 170, 560, 240, far)
    c.ellipse(540, HORIZON + 330, 1100, 330, near)


def _ground(c: Canvas, top, bottom) -> None:
    c.rect(0, HORIZON + 200, W, H, bottom)
    c.ellipse(540, HORIZON + 620, 1500, 560, top)
    c.rect(0, 1700, W, H, bottom)
    c.ellipse(540, 1700, 900, 120, top)


def _tufts(c: Canvas, seed: int, color, n=16, y0=1180, y1=1860) -> None:
    rng = random.Random(seed)
    for _ in range(n):
        x, y = rng.uniform(30, W - 30), rng.uniform(y0, y1)
        if 1250 < y < 1420 and 150 < x < 930:
            continue  # keep the acting area clean
        for dx, rot in ((-10, -22), (0, 0), (10, 22)):
            c.ellipse(x + dx, y - 12, 5, 16, color, xf=Xf.rotate(rot, x + dx, y))


def _flowers(c: Canvas, seed: int, n=10, size=26) -> None:
    rng = random.Random(seed)
    cols = ["pink", "yellow", "purple", "red", "white", "orange"]
    for _ in range(n):
        x, y = rng.uniform(40, W - 40), rng.choice([rng.uniform(1190, 1250), rng.uniform(1440, 1850)])
        draw_prop(c, "flower", x, y, size * rng.uniform(0.8, 1.2), rng.choice(cols))


def _cloud(c: Canvas, x, y, s, col=(255, 255, 255)) -> None:
    draw_prop(c, "cloud", x, y, s, col)


# ------------------------------------------------------------------ outdoors ---------
def build_meadow(c: Canvas) -> None:
    _hills(c, hex_rgb("#A8E0A0"), hex_rgb("#9ADB8A"))
    _ground(c, hex_rgb("#8FD67A"), hex_rgb("#7FCB6C"))
    _tufts(c, 11, hex_rgb("#6FBF63"))
    _flowers(c, 12, 9)


def amb_day(c: Canvas, t: float) -> None:
    draw_prop(c, "sun", 958, 128, 64, t=t)
    for i, (x0, y, s, v) in enumerate(((180, 470, 78, 9), (760, 830, 60, 6), (420, 140, 54, 12))):
        x = (x0 + t * v) % (W + 300) - 150
        _cloud(c, x, y + math.sin(t * 0.4 + i) * 5, s)


def build_garden(c: Canvas) -> None:
    _hills(c, hex_rgb("#B5E6A8"), hex_rgb("#9ADB8A"))
    for x in range(-10, W + 40, 72):
        c.shape([(x, 1170), (x + 26, 1140), (x + 52, 1170), (x + 52, 1290), (x, 1290)], (255, 255, 255), (214, 222, 235), 4)
    c.rect(0, 1206, W, 1224, (255, 255, 255))
    c.rect(0, 1256, W, 1274, (255, 255, 255))
    _ground(c, hex_rgb("#8FD67A"), hex_rgb("#7FCB6C"))
    _tufts(c, 21, hex_rgb("#6FBF63"), 10)
    _flowers(c, 22, 20, 30)


def build_pond(c: Canvas) -> None:
    _hills(c, hex_rgb("#A8E0A0"), hex_rgb("#9ADB8A"))
    _ground(c, hex_rgb("#8FD67A"), hex_rgb("#7FCB6C"))
    water = hex_rgb("#8CCFF5")
    c.ellipse(540, 1610, 470, 150, darken(water, 0.18))
    c.ellipse(540, 1602, 456, 140, water)
    c.ellipse(420, 1570, 120, 18, lighten(water, 0.4))
    for x, y in ((300, 1640), (700, 1600), (560, 1690)):
        c.ellipse(x, y, 44, 16, hex_rgb("#58B368"), darken("#58B368", 0.3), 3)
        c.ellipse(x + 10, y - 6, 12, 9, hex_rgb("#FF8FAB"))
    for x in (70, 110, 990, 1030):
        c.line([(x, 1560), (x + 6, 1420)], hex_rgb("#4CAF50"), 9)
        c.ellipse(x + 6, 1410, 10, 28, hex_rgb("#8A5A3A"))
    _tufts(c, 31, hex_rgb("#6FBF63"), 8, 1180, 1260)


def build_hilltop(c: Canvas) -> None:
    c.ellipse(140, HORIZON + 260, 520, 200, hex_rgb("#B5E6A8"))
    c.ellipse(980, HORIZON + 280, 480, 200, hex_rgb("#B5E6A8"))
    c.ellipse(540, 2050, 1150, 900, hex_rgb("#8FD67A"))
    c.ellipse(540, 2200, 1200, 760, hex_rgb("#86D072"))
    _tufts(c, 41, hex_rgb("#6FBF63"), 12, 1440, 1860)
    _flowers(c, 42, 6)


def build_forest(c: Canvas) -> None:
    for x, s in ((90, 1.25), (330, 1.0), (760, 1.05), (1000, 1.3)):
        trunk = hex_rgb("#9B6B43")
        c.shape([(x - 34 * s, 1320), (x + 34 * s, 1320), (x + 24 * s, 760), (x - 24 * s, 760)], trunk, darken(trunk, 0.3), 5)
        g = hex_rgb("#5FB56A")
        for dx, dy, r in ((-90, 0, 120), (90, 0, 120), (0, -110, 150), (0, 30, 120)):
            c.ellipse(x + dx * s, 760 + dy * s, r * s, r * s, g, darken(g, 0.25), 5)
        for dx, dy, r in ((-90, 0, 114), (90, 0, 114), (0, -110, 144), (0, 30, 114)):
            c.ellipse(x + dx * s, 760 + dy * s, r * s, r * s, g)
    _ground(c, hex_rgb("#7CCB6E"), hex_rgb("#6DBE62"))
    for x, y in ((180, 1480), (880, 1560), (620, 1760)):
        draw_prop(c, "mushroom", x, y, 34)
    _tufts(c, 51, hex_rgb("#5FB56A"), 14)


def build_rainy(c: Canvas) -> None:
    _hills(c, hex_rgb("#9DCFA0"), hex_rgb("#8FC98C"))
    _ground(c, hex_rgb("#86C97A"), hex_rgb("#78BD6E"))
    for x, y, s in ((230, 1500, 120), (800, 1620, 150), (560, 1790, 100)):
        draw_prop(c, "puddle", x, y - 40, s)
    _tufts(c, 61, hex_rgb("#69B45F"), 10)


def amb_rain(c: Canvas, t: float) -> None:
    grey = (226, 232, 242)
    for i, (x0, y, s, v) in enumerate(((200, 260, 120, 5), (640, 330, 140, 4), (980, 230, 110, 6))):
        _cloud(c, (x0 + t * v) % (W + 300) - 150, y, s, grey)
    rng = random.Random(7)
    drop = hex_rgb("#7FC4F2")
    for _ in range(46):
        x = rng.uniform(0, W)
        speed = rng.uniform(520, 700)
        y = (rng.uniform(0, 1500) + t * speed) % 1500 + 320
        if y < 1700:
            c.line([(x, y), (x - 5, y + 30)], drop, 5)


# -------------------------------------------------------------------- indoors --------
def _room(c: Canvas, wall, floor, skirting) -> None:
    c.rect(0, 0, W, 1210, wall)
    c.rect(0, 1210, W, H, floor)
    c.rect(0, 1196, W, 1222, skirting)


def _window(c: Canvas, x, y, night: bool) -> None:
    frame = (255, 255, 255)
    c.rrect(x - 170, y - 190, x + 170, y + 190, 26, frame, (205, 196, 220), 5)
    sky = hex_rgb("#2B3A7A") if night else hex_rgb("#BFE6FF")
    c.rrect(x - 146, y - 166, x + 146, y + 166, 14, sky)
    if night:
        draw_prop(c, "moon", x + 50, y - 60, 60)
        for sx, sy in ((-90, -100), (-60, 40), (80, 90), (-110, 110)):
            c.shape(star_points(x + sx, y + sy, 13, 6), hex_rgb("#FFE9A8"))
    else:
        c.ellipse(x, y + 190, 190, 120, hex_rgb("#9ADB8A"))
        _cloud(c, x - 50, y - 70, 50)
        c.rrect(x - 146, y + 100, x + 146, y + 166, 0, hex_rgb("#9ADB8A"))
    c.rect(x - 8, y - 166, x + 8, y + 166, frame)
    c.rect(x - 146, y - 8, x + 146, y + 8, frame)


def build_playroom(c: Canvas) -> None:
    _room(c, hex_rgb("#FFEFD6"), hex_rgb("#F3C98B"), hex_rgb("#FFFFFF"))
    for x in range(0, W, 180):
        c.line([(x, 1222), (x - 60, H)], darken("#F3C98B", 0.1), 4, caps=False)
    _window(c, 300, 560, night=False)
    shelf = hex_rgb("#C98B5B")
    c.rrect(650, 700, 1010, 724, 8, shelf, darken(shelf, 0.3), 4)
    c.rrect(650, 930, 1010, 954, 8, shelf, darken(shelf, 0.3), 4)
    for i, (name, col) in enumerate((("block", "red"), ("ball", "blue"), ("teddy", None))):
        draw_prop(c, name, 710 + i * 120, 650, 46, col)
    for i, (name, col) in enumerate((("book", "green"), ("drum", None), ("block", "yellow"))):
        draw_prop(c, name, 710 + i * 120, 880, 46, col)
    c.ellipse(540, 1420, 470, 150, hex_rgb("#9BD3F5"), darken("#9BD3F5", 0.2), 6)
    c.ellipse(540, 1420, 380, 112, hex_rgb("#BFE6FF"))


def build_bathroom(c: Canvas) -> None:
    _room(c, hex_rgb("#D9F3F5"), hex_rgb("#BFE3EA"), hex_rgb("#FFFFFF"))
    for x in range(0, W + 1, 120):
        c.line([(x, 0), (x, 1196)], (255, 255, 255), 5, caps=False)
    for y in range(76, 1196, 120):
        c.line([(0, y), (W, y)], (255, 255, 255), 5, caps=False)
    c.rrect(380, 300, 700, 700, 150, (255, 255, 255), (190, 214, 226), 8)
    c.rrect(402, 322, 678, 678, 130, hex_rgb("#EAF9FF"))
    c.line([(470, 420), (540, 370)], (255, 255, 255), 14)
    c.rrect(330, 960, 750, 1090, 40, (255, 255, 255), (190, 214, 226), 8)
    c.rect(500, 1090, 580, 1200, (255, 255, 255))
    c.line([(540, 960), (540, 900), (590, 900)], (190, 200, 214), 22)
    c.rrect(860, 780, 1000, 1000, 16, hex_rgb("#FFC2D1"), darken("#FFC2D1", 0.25), 5)
    c.ellipse(540, 1430, 420, 120, hex_rgb("#FFE9A8"), darken("#FFE9A8", 0.2), 6)


def build_bedroom(c: Canvas) -> None:
    _room(c, hex_rgb("#3A4A8C"), hex_rgb("#5A4A7A"), hex_rgb("#4A5AA0"))
    _window(c, 300, 540, night=True)
    wood = hex_rgb("#8A5A3A")
    c.rrect(600, 880, 1040, 1010, 30, wood, darken(wood, 0.3), 6)
    c.rrect(560, 990, 1070, 1230, 30, hex_rgb("#C9B8FF"), darken("#C9B8FF", 0.3), 6)
    c.rrect(620, 950, 800, 1050, 40, (255, 255, 255), (200, 200, 225), 5)
    for sx, sy in ((860, 1100), (960, 1160), (760, 1170)):
        c.shape(star_points(sx, sy, 22, 10), hex_rgb("#FFE9A8"))
    draw_prop(c, "lamp", 120, 1090, 110)
    c.ellipse(120, 1010, 150, 120, mix("#3A4A8C", "#FFE9A8", 0.16))
    draw_prop(c, "lamp", 120, 1090, 110)
    c.ellipse(540, 1440, 440, 130, hex_rgb("#7C6BB8"), darken("#7C6BB8", 0.25), 6)


def build_night(c: Canvas) -> None:
    _hills(c, hex_rgb("#2F6B5A"), hex_rgb("#2C6152"))
    _ground(c, hex_rgb("#2F7359"), hex_rgb("#2A664F"))
    _tufts(c, 71, hex_rgb("#245A46"), 14)
    draw_prop(c, "moon", 930, 150, 84)


def amb_night(c: Canvas, t: float) -> None:
    rng = random.Random(99)
    for i in range(30):
        x, y = rng.uniform(30, W - 30), rng.uniform(110, 1020)
        if abs(x - 930) < 120 and abs(y - 150) < 120:
            continue
        tw = 0.55 + 0.45 * math.sin(t * 1.3 + i * 1.7)
        c.shape(star_points(x, y, 6 + 7 * tw, 3 + 3 * tw), mix("#5C6BB5", "#FFF3C4", 0.35 + 0.65 * tw))
    for i in range(5):
        fx = 200 + i * 170 + math.sin(t * 0.5 + i) * 60
        fy = 1500 + math.cos(t * 0.4 + i * 2) * 90 + (i % 2) * 180
        glow = 0.5 + 0.5 * math.sin(t * 2.2 + i * 1.3)
        c.ellipse(fx, fy, 16 + glow * 8, 16 + glow * 8, mix("#2F7359", "#FFF3A0", 0.25 + 0.25 * glow))
        c.ellipse(fx, fy, 7, 7, mix("#FFE14A", "#FFFBD0", glow))


def amb_bedroom(c: Canvas, t: float) -> None:
    for i, (sx, sy) in enumerate(((210, 440), (240, 600), (390, 640), (190, 650))):
        tw = 0.5 + 0.5 * math.sin(t * 1.1 + i * 2.1)
        c.shape(star_points(sx, sy, 9 + 5 * tw, 4 + 2 * tw), mix("#2B3A7A", "#FFF3C4", 0.4 + 0.6 * tw))


DAY_SKY = [(0, "#BFE6FF"), (0.62, "#EAF8FF"), (1, "#EAF8FF")]
ENVS: dict[str, Env] = {
    "meadow":   Env("meadow", build_meadow, DAY_SKY, (104, 184, 96), amb_day),
    "garden":   Env("garden", build_garden, DAY_SKY, (104, 184, 96), amb_day),
    "pond":     Env("pond", build_pond, DAY_SKY, (104, 184, 96), amb_day),
    "hilltop":  Env("hilltop", build_hilltop, [(0, "#A9DCFF"), (0.7, "#E4F5FF"), (1, "#E4F5FF")], (104, 184, 96), amb_day),
    "forest":   Env("forest", build_forest, [(0, "#CDEFD8"), (0.6, "#E9F8E4"), (1, "#E9F8E4")], (92, 170, 88)),
    "rainy":    Env("rainy", build_rainy, [(0, "#B9C8DC"), (0.62, "#DCE6F0"), (1, "#DCE6F0")], (98, 168, 92), amb_rain),
    "playroom": Env("playroom", build_playroom, [(0, "#FFEFD6"), (1, "#FFEFD6")], (128, 190, 226), None, indoor=True),
    "bathroom": Env("bathroom", build_bathroom, [(0, "#D9F3F5"), (1, "#D9F3F5")], (228, 205, 140), None, indoor=True),
    "bedroom":  Env("bedroom", build_bedroom, [(0, "#3A4A8C"), (1, "#3A4A8C")], (98, 84, 152), amb_bedroom, dark=True, indoor=True),
    "night":    Env("night", build_night, [(0, "#1E2A5E"), (0.6, "#3A4A8C"), (1, "#3A4A8C")], (36, 88, 68), amb_night, dark=True),
}


@lru_cache(maxsize=12)
def background(key: str, ss: float = 2) -> Image.Image:
    """Static background at internal size (cached; callers must copy before drawing)."""
    from PIL import ImageDraw

    env = ENVS[key]
    base = vertical_gradient(round(W * ss), round(H * ss), env.sky)
    c = Canvas(W, H, ss, base=base)
    c.img = base  # draw directly onto the gradient (no extra copy)
    c.d = ImageDraw.Draw(base)
    env.build(c)
    return base


@lru_cache(maxsize=12)
def background_plate(key: str, ss: float = 2) -> Image.Image:
    """The background with a slight depth-of-field blur: sharp in the acting band around the
    ground line, softly blurred toward the far sky and the near foreground (cached)."""
    import numpy as np
    from PIL import ImageFilter

    base = background(key, ss)
    soft = base.filter(ImageFilter.GaussianBlur(2.0 * ss))
    ys = (np.arange(base.height, dtype=np.float32) + 0.5) / ss
    w = np.clip((np.abs(ys - (GROUND_Y - 40)) - 170) / 420, 0, 1) ** 1.2
    w = np.minimum(w, np.where(ys > GROUND_Y, 0.6, 1.0))
    mask = Image.fromarray(np.repeat((w * 255).round().astype("uint8")[:, None], base.width, axis=1), "L")
    return Image.composite(soft, base, mask)

