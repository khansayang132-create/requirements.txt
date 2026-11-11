"""Prop library: every object a story can show, drawn from basic shapes.

Each prop is a function ``(canvas, xf, color, t)`` drawing inside a local box of about
-100..100 units around the origin. ``draw_prop`` places it at a canvas position with a
size (half-height in output pixels), rotation and squash. ``color`` tints the props
that have a "main colour" (balloons, blocks, kites…); others ignore it.

The story engine may only reference names in ``PROPS``; ``spoken_name`` and ``LETTERS``
feed the alphabet and counting formats, so a prop added here is immediately usable.
"""

from __future__ import annotations

import math
from typing import Callable

from .canvas import Canvas, Xf, darken, ellipse_points, hex_rgb, lighten, mix

INK = (59, 51, 85)
WHITE = (255, 255, 255)

COLORS = {
    "red": "#F2545B", "orange": "#FF9A3D", "yellow": "#FFD43B", "green": "#51CF66", "blue": "#4D9DE0",
    "purple": "#9B7EDE", "pink": "#FF8FAB", "brown": "#B07A4F", "white": "#FDFDFD",
}


def star_points(cx, cy, ro, ri, n=5, rot=-90.0):
    pts = []
    for i in range(n * 2):
        r = ro if i % 2 == 0 else ri
        a = math.radians(rot + i * 180 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def heart_points(cx, cy, s, n=40):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * s / 17, cy + y * s / 17))
    return pts


def _o(col):
    return darken(col, 0.36)


# ------------------------------------------------------------------ shapes & toys ----
def p_circle(c, xf, col, t):
    c.ellipse(0, 0, 84, 84, col, _o(col), 6, xf, n=56)
    c.ellipse(-28, -30, 20, 14, lighten(col, 0.45), xf=xf)


def p_square(c, xf, col, t):
    c.shape([(-78, -78), (78, -78), (78, 78), (-78, 78)], col, _o(col), 6, xf)
    c.line([(-56, -56), (-20, -56)], lighten(col, 0.45), 10, xf)


def p_triangle(c, xf, col, t):
    c.shape([(0, -88), (92, 76), (-92, 76)], col, _o(col), 6, xf)
    c.line([(-14, -40), (-34, -4)], lighten(col, 0.45), 10, xf)


def p_rectangle(c, xf, col, t):
    c.shape([(-96, -56), (96, -56), (96, 56), (-96, 56)], col, _o(col), 6, xf)
    c.line([(-74, -34), (-30, -34)], lighten(col, 0.45), 10, xf)


def p_diamond(c, xf, col, t):
    c.shape([(0, -96), (70, 0), (0, 96), (-70, 0)], col, _o(col), 6, xf)
    c.line([(-12, -52), (-34, -18)], lighten(col, 0.45), 10, xf)


def p_oval(c, xf, col, t):
    c.ellipse(0, 0, 96, 62, col, _o(col), 6, xf, n=56)
    c.ellipse(-34, -22, 22, 12, lighten(col, 0.45), xf=xf)


def p_star(c, xf, col, t):
    c.shape(star_points(0, 4, 96, 44), col, _o(col), 6, xf)
    c.ellipse(-16, -14, 12, 9, lighten(col, 0.5), xf=xf)


def p_heart(c, xf, col, t):
    c.shape(heart_points(0, 6, 92), col, _o(col), 6, xf)
    c.ellipse(-36, -34, 16, 11, lighten(col, 0.5), xf=xf)


def p_balloon(c, xf, col, t):
    sway = math.sin(t * 1.6) * 6
    c.line([(0, 62), (sway, 96), (-sway, 132), (sway * 0.6, 168)], darken(col, 0.5), 3.5, xf)
    c.shape([(-12, 70), (12, 70), (0, 54)], darken(col, 0.2), _o(col), 4, xf)
    c.ellipse(0, -12, 68, 78, col, _o(col), 6, xf, n=56)
    c.ellipse(-26, -40, 15, 22, lighten(col, 0.55), xf=Xf.rotate(24, -26, -40).then(xf))


def p_ball(c, xf, col, t):
    c.ellipse(0, 0, 82, 82, col, _o(col), 6, xf, n=56)
    band = lighten(col, 0.55)
    c.line([(-78, -22), (-30, -44), (30, -44), (78, -22)], band, 14, xf, caps=False)
    c.line([(-78, 26), (-30, 46), (30, 46), (78, 26)], band, 14, xf, caps=False)
    c.ellipse(0, 0, 82, 82, None, _o(col), 6, xf, n=56)


def p_block(c, xf, col, t):
    top = lighten(col, 0.3)
    side = darken(col, 0.16)
    c.shape([(-70, -40), (40, -40), (40, 70), (-70, 70)], col, _o(col), 6, xf)
    c.shape([(-70, -40), (-36, -76), (74, -76), (40, -40)], top, _o(col), 6, xf)
    c.shape([(40, -40), (74, -76), (74, 34), (40, 70)], side, _o(col), 6, xf)
    c.shape(star_points(-15, 16, 30, 14), lighten(col, 0.6), xf=xf)


def p_kite(c, xf, col, t):
    sway = math.sin(t * 2.0) * 8
    c.line([(0, 84), (10 + sway, 120), (-8 - sway, 150), (6 + sway, 182)], darken(col, 0.45), 3.5, xf)
    for i, (bx, by) in enumerate(((10 + sway, 120), (-8 - sway, 150))):
        bc = hex_rgb(COLORS["yellow" if i == 0 else "pink"])
        c.shape([(bx - 16, by - 9), (bx, by), (bx - 16, by + 9)], bc, xf=xf)
        c.shape([(bx + 16, by - 9), (bx, by), (bx + 16, by + 9)], bc, xf=xf)
    c.shape([(0, -96), (64, -14), (0, 86), (-64, -14)], col, _o(col), 6, xf)
    c.shape([(0, -96), (64, -14), (0, -14)], lighten(col, 0.3), xf=xf)
    c.line([(0, -92), (0, 82)], _o(col), 4, xf)
    c.line([(-60, -14), (60, -14)], _o(col), 4, xf)


def p_teddy(c, xf, col, t):
    b = hex_rgb("#D9A066")
    o = _o(b)
    for sx in (-1, 1):
        c.ellipse(sx * 46, -72, 22, 22, b, o, 5, xf)
        c.ellipse(sx * 62, 6, 20, 30, b, o, 5, Xf.rotate(sx * -30, sx * 62, 6).then(xf))
        c.ellipse(sx * 36, 78, 26, 20, b, o, 5, xf)
    c.ellipse(0, 26, 56, 60, b, o, 5, xf)
    c.ellipse(0, 32, 30, 34, lighten(b, 0.4), xf=xf)
    c.ellipse(0, -44, 54, 48, b, o, 5, xf)
    c.ellipse(0, -30, 22, 17, lighten(b, 0.45), xf=xf)
    c.ellipse(0, -36, 8, 6, INK, xf=xf)
    for sx in (-1, 1):
        c.ellipse(sx * 20, -54, 6, 7, INK, xf=xf)


def p_drum(c, xf, col, t):
    col = hex_rgb(COLORS["red"]) if col is None else col
    c.shape([(-74, -30), (74, -30), (74, 50), (-74, 50)], col, _o(col), 6, xf)
    c.ellipse(0, 50, 74, 22, col, _o(col), 6, xf)
    for x0, x1 in ((-74, -37), (-37, 0), (0, 37), (37, 74)):
        c.line([(x0, -22), ((x0 + x1) / 2, 44), (x1, -22)], hex_rgb("#FFD43B"), 5, xf, caps=False)
    c.ellipse(0, -30, 74, 22, hex_rgb("#FFF6E3"), _o(col), 6, xf)
    c.line([(-30, -86), (20, -34)], hex_rgb("#B07A4F"), 9, xf)
    c.line([(40, -90), (-8, -40)], hex_rgb("#B07A4F"), 9, xf)


def p_boat(c, xf, col, t):
    c.shape([(-90, 14), (90, 14), (60, 70), (-60, 70)], col, _o(col), 6, xf)
    c.line([(0, 14), (0, -92)], hex_rgb("#B07A4F"), 8, xf)
    c.shape([(8, -88), (8, -4), (72, -4)], WHITE, (170, 170, 190), 5, xf)
    c.shape([(-8, -70), (-8, -4), (-52, -4)], lighten(col, 0.6), (170, 170, 190), 5, xf)


def p_book(c, xf, col, t):
    c.shape([(-88, -60), (0, -44), (0, 68), (-88, 52)], WHITE, _o(col), 6, xf)
    c.shape([(88, -60), (0, -44), (0, 68), (88, 52)], WHITE, _o(col), 6, xf)
    for y in (-26, -4, 18):
        c.line([(-70, y - 6), (-18, y + 2)], mix(col, WHITE, 0.3), 6, xf)
        c.line([(70, y - 6), (18, y + 2)], mix(col, WHITE, 0.3), 6, xf)
    c.shape([(-96, 50), (0, 68), (96, 50), (96, 64), (0, 82), (-96, 64)], col, _o(col), 5, xf)


def p_bucket(c, xf, col, t):
    c.line([(-56, -40), (-40, -92), (40, -92), (56, -40)], _o(col), 7, xf)
    c.shape([(-64, -44), (64, -44), (48, 76), (-48, 76)], col, _o(col), 6, xf)
    c.ellipse(0, -44, 64, 16, lighten(col, 0.3), _o(col), 6, xf)


def p_cup(c, xf, col, t):
    c.ellipse(62, 6, 30, 36, None, _o(col), 12, xf)
    c.shape([(-58, -56), (58, -56), (46, 70), (-46, 70)], col, _o(col), 6, xf)
    c.ellipse(0, -56, 58, 14, lighten(col, 0.5), _o(col), 6, xf)


def p_sock(c, xf, col, t):
    c.shape([(-34, -90), (30, -90), (30, 10), (78, 40), (70, 84), (-10, 84), (-34, 50)], col, _o(col), 6, xf)
    c.shape([(-34, -90), (30, -90), (30, -60), (-34, -60)], lighten(col, 0.5), _o(col), 5, xf)
    c.line([(-28, 6), (24, 6)], lighten(col, 0.4), 9, xf)


def p_hat(c, xf, col, t):
    c.ellipse(0, 46, 96, 24, col, _o(col), 6, xf)
    c.shape(ellipse_points(0, 40, 60, 96, 40)[20:] + [(60, 40)], col, _o(col), 6, xf)
    c.line([(-58, 26), (58, 26)], lighten(col, 0.55), 14, xf, caps=False)


def p_bell(c, xf, col, t):
    col = hex_rgb(COLORS["yellow"])
    swing = math.sin(t * 5) * 6
    R = Xf.rotate(swing, 0, -80).then(xf)
    c.ellipse(0, 70, 16, 16, darken(col, 0.3), xf=R)
    c.shape([(-18, -80), (18, -80), (50, -20), (62, 50), (-62, 50), (-50, -20)], col, _o(col), 6, R)
    c.ellipse(0, 50, 70, 14, lighten(col, 0.2), _o(col), 6, R)
    c.ellipse(0, -84, 14, 14, col, _o(col), 5, R)


def p_key(c, xf, col, t):
    col = hex_rgb(COLORS["yellow"])
    c.line([(0, -10), (0, 88)], _o(col), 22, xf)
    c.line([(0, -10), (0, 88)], col, 12, xf)
    c.line([(0, 60), (30, 60)], col, 12, xf)
    c.line([(0, 84), (24, 84)], col, 12, xf)
    c.ellipse(0, -48, 44, 44, col, _o(col), 6, xf)
    c.ellipse(0, -48, 18, 18, lighten(col, 0.75), _o(col), 5, xf)


def p_umbrella(c, xf, col, t):
    c.line([(0, -60), (0, 70), (10, 88), (28, 84)], hex_rgb("#8A6A4A"), 9, xf)
    top = [(x, y) for x, y in ellipse_points(0, -20, 98, 76, 48) if y <= -20]
    top.sort(key=lambda q: q[0])
    c.shape(top + [(66, -8), (33, -22), (0, -8), (-33, -22), (-66, -8)], col, _o(col), 6, xf)
    c.line([(0, -96), (0, -110)], _o(col), 8, xf)
    c.line([(-33, -22), (-24, -84)], lighten(col, 0.35), 5, xf)
    c.line([(33, -22), (24, -84)], lighten(col, 0.35), 5, xf)


# --------------------------------------------------------------------- nature --------
def p_flower(c, xf, col, t):
    sway = math.sin(t * 1.4) * 4
    R = Xf.rotate(sway, 0, 96).then(xf)
    g = hex_rgb("#4CAF50")
    c.line([(0, 0), (0, 96)], g, 10, R)
    c.ellipse(26, 56, 26, 11, g, xf=Xf.rotate(-30, 26, 56).then(R))
    for i in range(6):
        a = math.radians(i * 60 + 30)
        c.ellipse(46 * math.cos(a), -18 + 46 * math.sin(a), 30, 30, col, _o(col), 5, R)
    c.ellipse(0, -18, 26, 26, hex_rgb("#FFD43B"), darken("#FFD43B", 0.3), 5, R)


def p_tree(c, xf, col, t):
    c.shape([(-20, 96), (20, 96), (14, 0), (-14, 0)], hex_rgb("#9B6B43"), darken("#9B6B43", 0.3), 6, xf)
    g = hex_rgb("#58B368")
    for cx, cy, r in ((-44, -6, 46), (44, -6, 46), (0, -52, 58), (0, 2, 44)):
        c.ellipse(cx, cy, r, r, g, darken(g, 0.3), 6, xf)
    for cx, cy, r in ((-44, -6, 42), (44, -6, 42), (0, -52, 54), (0, 2, 40)):
        c.ellipse(cx, cy, r, r, g, xf=xf)
    c.ellipse(-18, -66, 16, 11, lighten(g, 0.35), xf=xf)


def p_leaf(c, xf, col, t):
    col = hex_rgb("#58B368") if col is None else col
    pts = [(0, -92), (52, -40), (58, 20), (0, 92), (-58, 20), (-52, -40)]
    c.shape(pts, col, _o(col), 6, xf)
    c.line([(0, -70), (0, 84)], darken(col, 0.25), 5, xf)
    for y in (-30, 6, 40):
        c.line([(0, y), (30, y - 22)], darken(col, 0.25), 4, xf)
        c.line([(0, y), (-30, y - 22)], darken(col, 0.25), 4, xf)


def p_butterfly(c, xf, col, t):
    flap = 0.55 + 0.45 * abs(math.sin(t * 7))
    for sx in (-1, 1):
        W = Xf.scale(sx * flap, 1).then(xf)
        c.ellipse(46, -30, 44, 50, col, _o(col), 5, W)
        c.ellipse(38, 40, 32, 34, lighten(col, 0.25), _o(col), 5, W)
        c.ellipse(48, -32, 16, 18, lighten(col, 0.6), xf=W)
    c.ellipse(0, 4, 12, 56, INK, xf=xf)
    c.line([(-4, -48), (-18, -84)], INK, 4, xf)
    c.line([(4, -48), (18, -84)], INK, 4, xf)


def p_ladybug(c, xf, col, t):
    r = hex_rgb(COLORS["red"])
    c.ellipse(0, -52, 34, 30, INK, xf=xf)
    c.ellipse(0, 10, 74, 68, r, _o(r), 6, xf)
    c.line([(0, -56), (0, 76)], INK, 6, xf)
    for dx, dy in ((-34, -14), (34, -14), (-28, 34), (28, 34)):
        c.ellipse(dx, dy, 13, 13, INK, xf=xf)
    for sx in (-1, 1):
        c.ellipse(sx * 13, -60, 6, 6, WHITE, xf=xf)
        c.line([(sx * 10, -78), (sx * 24, -96)], INK, 4, xf)


def p_snail(c, xf, col, t):
    b = hex_rgb("#F6C28B")
    c.shape([(-92, 70), (-80, 36), (40, 36), (70, -4), (92, 4), (84, 70)], b, _o(b), 6, xf)
    c.line([(70, -4), (64, -40)], _o(b), 6, xf)
    c.line([(88, 2), (96, -34)], _o(b), 6, xf)
    c.ellipse(64, -44, 8, 8, INK, xf=xf)
    c.ellipse(96, -38, 8, 8, INK, xf=xf)
    sh = hex_rgb(COLORS["purple"]) if col is None else col
    c.ellipse(-20, 0, 62, 60, sh, _o(sh), 6, xf)
    c.ellipse(-20, 0, 36, 34, lighten(sh, 0.3), _o(sh), 5, xf)
    c.ellipse(-20, 0, 12, 11, sh, _o(sh), 4, xf)


def p_frog(c, xf, col, t):
    g = hex_rgb("#6CCB5F")
    c.ellipse(0, 30, 84, 58, g, _o(g), 6, xf)
    for sx in (-1, 1):
        c.ellipse(sx * 70, 74, 34, 14, g, _o(g), 5, xf)
        c.ellipse(sx * 40, -30, 30, 30, g, _o(g), 6, xf)
        c.ellipse(sx * 40, -32, 17, 17, WHITE, xf=xf)
        c.ellipse(sx * 40, -30, 9, 10, INK, xf=xf)
    c.line([(-36, 34), (0, 50), (36, 34)], INK, 6, xf)
    c.ellipse(0, 54, 40, 22, lighten(g, 0.45), xf=xf)


def p_ant(c, xf, col, t):
    b = hex_rgb("#7A4B3A")
    for dx in (-30, 0, 30):
        c.line([(dx, 10), (dx - 10, 60)], INK, 5, xf)
        c.line([(dx + 8, 10), (dx + 18, 60)], INK, 5, xf)
    c.ellipse(-52, 4, 34, 28, b, _o(b), 5, xf)
    c.ellipse(0, 8, 24, 20, b, _o(b), 5, xf)
    c.ellipse(46, -8, 32, 30, b, _o(b), 5, xf)
    c.ellipse(56, -14, 7, 8, WHITE, xf=xf)
    c.ellipse(58, -13, 4, 5, INK, xf=xf)
    c.line([(52, -36), (44, -70)], INK, 4, xf)
    c.line([(66, -32), (78, -64)], INK, 4, xf)


def p_fish(c, xf, col, t):
    wag = math.sin(t * 6) * 10
    c.shape([(-50, 0), (-98, -44 + wag), (-98, 44 + wag)], lighten(col, 0.2), _o(col), 6, xf)
    c.ellipse(8, 0, 76, 50, col, _o(col), 6, xf)
    c.shape([(0, -46), (30, -78), (40, -42)], lighten(col, 0.2), _o(col), 5, xf)
    c.ellipse(46, -12, 13, 14, WHITE, xf=xf)
    c.ellipse(49, -11, 7, 8, INK, xf=xf)
    c.line([(-8, -26), (4, 0), (-8, 26)], lighten(col, 0.45), 6, xf)


def p_mushroom(c, xf, col, t):
    r = hex_rgb(COLORS["red"])
    c.shape([(-26, 0), (26, 0), (32, 84), (-32, 84)], hex_rgb("#FFF1DA"), darken("#FFF1DA", 0.3), 6, xf)
    cap = [(x, y) for x, y in ellipse_points(0, 6, 92, 84, 48) if y <= 6]
    cap.sort(key=lambda q: q[0])
    c.shape(cap, r, _o(r), 6, xf)
    for dx, dy, rr in ((-40, -26, 13), (10, -48, 15), (48, -14, 10)):
        c.ellipse(dx, dy, rr, rr, WHITE, xf=xf)


def p_acorn(c, xf, col, t):
    b = hex_rgb("#C98B5B")
    c.ellipse(0, 22, 54, 66, b, _o(b), 6, xf)
    cap = [(x, y) for x, y in ellipse_points(0, -14, 64, 50, 40) if y <= -10]
    cap.sort(key=lambda q: q[0])
    c.shape(cap, darken(b, 0.3), darken(b, 0.5), 6, xf)
    c.line([(0, -62), (6, -86)], darken(b, 0.5), 8, xf)
    c.ellipse(-18, 14, 10, 18, lighten(b, 0.35), xf=xf)


def p_nest(c, xf, col, t):
    b = hex_rgb("#B07A4F")
    for dx in (-30, 0, 30):
        e = hex_rgb("#DDF2FF")
        c.ellipse(dx, -8, 22, 28, e, darken(e, 0.3), 5, xf)
    bowl = [(x, y) for x, y in ellipse_points(0, 0, 94, 76, 48) if y >= 0]
    bowl.sort(key=lambda q: -q[0])
    c.shape(bowl, b, _o(b), 6, xf)
    for i in range(-3, 4):
        c.line([(i * 24 - 10, 14), (i * 24 + 12, 44)], darken(b, 0.22), 5, xf)


def p_sprout(c, xf, col, t):
    g = hex_rgb("#58B368")
    c.ellipse(0, 78, 84, 22, hex_rgb("#9B6B43"), darken("#9B6B43", 0.3), 6, xf)
    grow = 0.85 + 0.15 * math.sin(t * 2)
    c.line([(0, 74), (0, 74 - 96 * grow)], g, 10, xf)
    for sx in (-1, 1):
        c.ellipse(sx * 30, 74 - 96 * grow - 8, 32, 16, g, _o(g), 5, Xf.rotate(sx * -28, sx * 30, 74 - 96 * grow - 8).then(xf))


def p_seed(c, xf, col, t):
    b = hex_rgb("#9B6B43")
    c.ellipse(0, 40, 90, 26, b, _o(b), 6, xf)
    s = hex_rgb("#E9C46A")
    c.ellipse(0, 0, 22, 32, s, _o(s), 5, Xf.rotate(20, 0, 0).then(xf))


# ------------------------------------------------------------------------ food -------
def p_apple(c, xf, col, t):
    col = hex_rgb(COLORS["red"]) if col is None else col
    c.line([(0, -52), (8, -86)], hex_rgb("#8A5A3A"), 9, xf)
    lf = hex_rgb("#58B368")
    c.ellipse(34, -76, 26, 12, lf, _o(lf), 4, Xf.rotate(-25, 34, -76).then(xf))
    c.ellipse(-30, 10, 52, 66, col, _o(col), 6, xf)
    c.ellipse(30, 10, 52, 66, col, _o(col), 6, xf)
    c.ellipse(0, 12, 60, 62, col, xf=xf)
    c.ellipse(-38, -18, 12, 20, lighten(col, 0.5), xf=Xf.rotate(20, -38, -18).then(xf))


def p_orange(c, xf, col, t):
    o = hex_rgb(COLORS["orange"])
    c.ellipse(0, 6, 80, 78, o, _o(o), 6, xf)
    lf = hex_rgb("#58B368")
    c.ellipse(16, -76, 24, 11, lf, _o(lf), 4, Xf.rotate(-20, 16, -76).then(xf))
    c.ellipse(-30, -24, 14, 10, lighten(o, 0.5), xf=xf)
    for dx, dy in ((20, 20), (-10, 40), (34, -10)):
        c.ellipse(dx, dy, 3, 3, darken(o, 0.2), xf=xf)


def p_banana(c, xf, col, t):
    y = hex_rgb(COLORS["yellow"])
    outer = [(-86, -40), (-60, 30), (0, 70), (64, 62), (92, 20)]
    inner = [(84, 0), (50, 22), (0, 28), (-40, 0), (-66, -52)]
    c.shape(outer + inner, y, _o(y), 6, xf)
    c.line([(-78, -50), (-90, -66)], hex_rgb("#8A6A4A"), 10, xf)
    c.line([(-44, 20), (10, 48), (60, 42)], lighten(y, 0.5), 6, xf)


def p_carrot(c, xf, col, t):
    o = hex_rgb(COLORS["orange"])
    g = hex_rgb("#58B368")
    for rot in (-28, 0, 28):
        c.ellipse(0, -84, 12, 34, g, _o(g), 4, Xf.rotate(rot, 0, -56).then(xf))
    c.shape([(-40, -56), (40, -56), (6, 96), (-6, 96)], o, _o(o), 6, xf)
    for yy, w in ((-24, 22), (10, 16), (44, 10)):
        c.line([(-w, yy), (w * 0.2, yy + 5)], darken(o, 0.2), 4, xf)


def p_cupcake(c, xf, col, t):
    col = hex_rgb(COLORS["pink"]) if col is None else col
    base = hex_rgb("#F6C28B")
    c.shape([(-58, 6), (58, 6), (42, 88), (-42, 88)], base, _o(base), 6, xf)
    for dx in (-30, 0, 30):
        c.line([(dx, 14), (dx * 0.8, 82)], darken(base, 0.2), 4, xf)
    c.ellipse(0, -4, 72, 34, col, _o(col), 6, xf)
    c.ellipse(0, -36, 52, 30, col, _o(col), 6, xf)
    c.ellipse(0, -62, 30, 22, col, _o(col), 6, xf)
    c.ellipse(0, -88, 13, 13, hex_rgb(COLORS["red"]), darken(COLORS["red"], 0.3), 4, xf)


def p_icecream(c, xf, col, t):
    col = hex_rgb(COLORS["pink"]) if col is None else col
    cone = hex_rgb("#E9B872")
    c.shape([(-46, -6), (46, -6), (0, 96)], cone, _o(cone), 6, xf)
    c.line([(-24, 10), (14, 60)], darken(cone, 0.2), 4, xf)
    c.line([(24, 10), (-14, 60)], darken(cone, 0.2), 4, xf)
    c.ellipse(0, -36, 58, 54, col, _o(col), 6, xf)
    c.ellipse(-20, -56, 14, 10, lighten(col, 0.5), xf=xf)
    c.ellipse(0, -92, 12, 12, hex_rgb(COLORS["red"]), darken(COLORS["red"], 0.3), 4, xf)


def p_egg(c, xf, col, t):
    e = hex_rgb("#FFF6E3")
    c.ellipse(0, 6, 62, 82, e, darken(e, 0.3), 6, xf)
    c.ellipse(-20, -30, 12, 20, WHITE, xf=xf)


def p_jar(c, xf, col, t):
    g = hex_rgb("#CFEFFF")
    c.shape([(-56, -50), (56, -50), (62, 84), (-62, 84)], g, darken(g, 0.35), 6, xf)
    c.shape([(-56, 0), (56, 0), (62, 84), (-62, 84)], hex_rgb("#FFC145"), xf=xf)
    c.shape([(-56, -50), (56, -50), (62, 84), (-62, 84)], None, darken(g, 0.35), 6, xf)
    lid = hex_rgb(COLORS["red"]) if col is None else col
    c.shape([(-62, -80), (62, -80), (62, -50), (-62, -50)], lid, _o(lid), 6, xf)


# ----------------------------------------------------------------- sky & weather -----
def p_sun(c, xf, col, t):
    y = hex_rgb("#FFD95A")
    R = Xf.rotate(t * 12).then(xf)
    for i in range(10):
        a = math.radians(i * 36)
        c.line([(70 * math.cos(a), 70 * math.sin(a)), (98 * math.cos(a), 98 * math.sin(a))], y, 13, R)
    c.ellipse(0, 0, 60, 60, y, darken(y, 0.22), 5, xf)
    for sx in (-1, 1):
        c.ellipse(sx * 20, -8, 6, 8, INK, xf=xf)
        c.ellipse(sx * 34, 10, 10, 6, hex_rgb("#FFB37A"), xf=xf)
    c.line([(-16, 16), (0, 24), (16, 16)], INK, 5, xf)


def p_moon(c, xf, col, t):
    y = hex_rgb("#FFE9A8")
    c.ellipse(0, 0, 84, 84, y, darken(y, 0.25), 6, xf)
    for dx, dy, r in ((-24, -24, 14), (26, 6, 18), (-10, 38, 10)):
        c.ellipse(dx, dy, r, r, darken(y, 0.1), xf=xf)


def p_cloud(c, xf, col, t):
    w = WHITE if col is None else col
    o = darken(w, 0.16)
    for cx, cy, r in ((-52, 14, 40), (0, -12, 54), (52, 14, 40), (0, 26, 44)):
        c.ellipse(cx, cy, r + 5, r + 5, o, xf=xf)
    for cx, cy, r in ((-52, 14, 40), (0, -12, 54), (52, 14, 40), (0, 26, 44)):
        c.ellipse(cx, cy, r, r, w, xf=xf)


def p_raindrop(c, xf, col, t):
    b = hex_rgb("#6FC3F7")
    pts = [(0, -90)] + [(x, y) for x, y in ellipse_points(0, 22, 56, 60, 36) if y >= 0 or abs(x) > 40]
    pts.sort(key=lambda q: math.atan2(q[1] - 10, q[0]))
    c.shape(pts, b, _o(b), 6, xf)
    c.ellipse(-20, 20, 10, 16, lighten(b, 0.55), xf=xf)


def p_rainbow(c, xf, col, t):
    bands = ["red", "orange", "yellow", "green", "blue", "purple"]
    for i, name in enumerate(bands):
        r = 98 - i * 12
        arc = [(x, y) for x, y in ellipse_points(0, 40, r, r, 64) if y <= 40]
        arc.sort(key=lambda q: q[0])
        c.line(arc, hex_rgb(COLORS[name]), 13, xf, caps=False)


def p_puddle(c, xf, col, t):
    b = hex_rgb("#8CCFF5")
    c.ellipse(0, 40, 98, 30, b, darken(b, 0.25), 5, xf)
    ripple = (t * 0.8) % 1.0
    c.ellipse(0, 40, 30 + 50 * ripple, 9 + 14 * ripple, None, lighten(b, 0.5), 4, xf)


def p_firefly(c, xf, col, t):
    glow = 0.5 + 0.5 * math.sin(t * 4)
    y = mix("#FFF3A0", "#FFE14A", glow)
    c.ellipse(0, 10, 46 + glow * 14, 46 + glow * 14, mix((40, 44, 90), y, 0.25 + 0.2 * glow), xf=xf)
    c.ellipse(0, 10, 26, 26, y, xf=xf)
    c.ellipse(0, -22, 13, 12, INK, xf=xf)
    for sx in (-1, 1):
        c.ellipse(sx * 22, -10, 20, 10, (220, 235, 255), xf=Xf.rotate(sx * 30, sx * 22, -10).then(xf))


# ----------------------------------------------------------------- home & habits -----
def p_toothbrush(c, xf, col, t):
    col = hex_rgb(COLORS["blue"]) if col is None else col
    R = Xf.rotate(-35).then(xf)
    c.line([(-20, 0), (96, 0)], _o(col), 26, R)
    c.line([(-20, 0), (96, 0)], col, 16, R)
    c.shape([(-96, -14), (-22, -14), (-22, 14), (-96, 14)], WHITE, (170, 170, 190), 5, R)
    for x in (-84, -66, -48, -30):
        c.line([(x, -14), (x, -42)], hex_rgb("#BDEBFF"), 12, R, caps=False)


def p_soap(c, xf, col, t):
    s = hex_rgb("#FFC2D1") if col is None else col
    c.shape([(-70, -20), (70, -20), (80, 50), (-80, 50)], s, _o(s), 6, xf)
    c.line([(-40, 4), (20, 4)], lighten(s, 0.5), 9, xf)
    for dx, dy, r in ((-50, -56, 18), (-10, -74, 26), (40, -52, 16)):
        c.ellipse(dx, dy, r, r, (236, 248, 255), (150, 200, 235), 4, xf)
        c.ellipse(dx - r * 0.3, dy - r * 0.3, r * 0.25, r * 0.25, WHITE, xf=xf)


def p_bubbles(c, xf, col, t):
    for i, (dx, dy, r) in enumerate(((-50, 30, 30), (20, -10, 44), (56, 50, 22), (-20, -62, 24))):
        bob = math.sin(t * 2 + i) * 6
        c.ellipse(dx, dy + bob, r, r, (236, 248, 255), (150, 200, 235), 4, xf)
        c.ellipse(dx - r * 0.3, dy + bob - r * 0.3, r * 0.25, r * 0.25, WHITE, xf=xf)


def p_towel(c, xf, col, t):
    col = hex_rgb(COLORS["green"]) if col is None else col
    c.shape([(-64, -80), (64, -80), (64, 80), (-64, 80)], col, _o(col), 6, xf)
    for y in (-48, 48):
        c.line([(-64, y), (64, y)], lighten(col, 0.5), 12, xf, caps=False)
    c.shape([(-64, -80), (64, -80), (64, 80), (-64, 80)], None, _o(col), 6, xf)


def p_pillow(c, xf, col, t):
    col = hex_rgb("#C9B8FF") if col is None else col
    c.shape([(-90, -40), (-60, -52), (60, -52), (90, -40), (84, 44), (60, 54), (-60, 54), (-84, 44)], col, _o(col), 6, xf)
    c.line([(-50, -20), (-10, -24)], lighten(col, 0.5), 9, xf)


def p_lamp(c, xf, col, t):
    col = hex_rgb("#FFD95A") if col is None else col
    c.line([(0, -10), (0, 76)], hex_rgb("#8A6A4A"), 10, xf)
    c.ellipse(0, 82, 46, 12, hex_rgb("#8A6A4A"), darken("#8A6A4A", 0.3), 5, xf)
    c.shape([(-34, -84), (34, -84), (62, -6), (-62, -6)], col, _o(col), 6, xf)


def p_bed(c, xf, col, t):
    col = hex_rgb("#9B7EDE") if col is None else col
    wood = hex_rgb("#B07A4F")
    c.shape([(-98, -40), (-78, -40), (-78, 70), (-98, 70)], wood, _o(wood), 5, xf)
    c.shape([(78, -10), (98, -10), (98, 70), (78, 70)], wood, _o(wood), 5, xf)
    c.shape([(-80, 10), (80, 10), (80, 52), (-80, 52)], WHITE, (170, 170, 190), 5, xf)
    c.ellipse(-48, 4, 28, 14, WHITE, (170, 170, 190), 5, xf)
    c.shape([(-20, 2), (80, 2), (80, 52), (-20, 52)], col, _o(col), 5, xf)
    c.shape(star_points(34, 28, 14, 6), hex_rgb("#FFD95A"), xf=xf)


def p_number(c, xf, col, t):  # drawn as text by the stage; placeholder disc for sheets
    c.ellipse(0, 0, 80, 80, col, _o(col), 6, xf)


PROPS: dict[str, Callable] = {
    "circle": p_circle, "square": p_square, "triangle": p_triangle, "rectangle": p_rectangle, "diamond": p_diamond,
    "oval": p_oval, "star": p_star, "heart": p_heart, "balloon": p_balloon, "ball": p_ball, "block": p_block,
    "kite": p_kite, "teddy": p_teddy, "drum": p_drum, "boat": p_boat, "book": p_book, "bucket": p_bucket,
    "cup": p_cup, "sock": p_sock, "hat": p_hat, "bell": p_bell, "key": p_key, "umbrella": p_umbrella,
    "flower": p_flower, "tree": p_tree, "leaf": p_leaf, "butterfly": p_butterfly, "ladybug": p_ladybug,
    "snail": p_snail, "frog": p_frog, "ant": p_ant, "fish": p_fish, "mushroom": p_mushroom, "acorn": p_acorn,
    "nest": p_nest, "sprout": p_sprout, "seed": p_seed, "apple": p_apple, "orange": p_orange, "banana": p_banana,
    "carrot": p_carrot, "cupcake": p_cupcake, "icecream": p_icecream, "egg": p_egg, "jar": p_jar, "sun": p_sun,
    "moon": p_moon, "cloud": p_cloud, "raindrop": p_raindrop, "rainbow": p_rainbow, "puddle": p_puddle,
    "firefly": p_firefly, "toothbrush": p_toothbrush, "soap": p_soap, "bubbles": p_bubbles, "towel": p_towel,
    "pillow": p_pillow, "lamp": p_lamp, "bed": p_bed,
}

# Props that take a story colour (so "a red balloon" is really red).
TINTABLE = {"circle", "square", "triangle", "rectangle", "diamond", "oval", "star", "heart", "balloon", "ball",
            "block", "kite", "boat", "book", "bucket", "cup", "sock", "hat", "umbrella", "flower", "butterfly", "fish"}

SPOKEN = {"icecream": "ice cream", "ladybug": "ladybug", "toothbrush": "toothbrush", "raindrop": "raindrop",
          "cupcake": "cupcake", "firefly": "firefly"}
PLURAL = {"butterfly": "butterflies", "fish": "fish", "leaf": "leaves", "teddy": "teddies", "ladybug": "ladybugs",
          "firefly": "fireflies", "toothbrush": "toothbrushes", "icecream": "ice creams", "bubbles": "bubbles"}

# Alphabet: only words we can actually draw (props) or who live in the meadow (characters).
LETTERS = {
    "A": ["apple", "ant", "acorn"], "B": ["ball", "balloon", "butterfly", "boat", "book", "bell", "bucket", "bed", "banana"],
    "C": ["carrot", "cloud", "cupcake", "cup", "circle"], "D": ["drum", "diamond"], "E": ["egg"],
    "F": ["fish", "flower", "frog", "firefly"], "H": ["hat", "heart"], "I": ["icecream"], "J": ["jar"],
    "K": ["kite", "key"], "L": ["leaf", "ladybug", "lamp"], "M": ["moon", "mushroom"], "N": ["nest"],
    "O": ["orange", "oval"], "P": ["puddle", "pillow"], "R": ["rainbow", "raindrop", "rectangle"],
    "S": ["sun", "star", "snail", "sock", "soap", "square", "seed"], "T": ["tree", "teddy", "toothbrush", "triangle", "towel"],
    "U": ["umbrella"],
}


def spoken_name(prop: str, count: int = 1) -> str:
    if count != 1:
        return PLURAL.get(prop, SPOKEN.get(prop, prop) + "s")
    return SPOKEN.get(prop, prop)


def draw_prop(c: Canvas, name: str, x: float, y: float, size: float, color=None, t: float = 0.0,
              rot: float = 0.0, squash: float = 0.0, flip: bool = False) -> None:
    fn = PROPS[name]
    k = size / 100.0
    xf = Xf.scale((-k if flip else k) * (1 + squash * 0.4), k * (1 - squash * 0.4))
    if rot:
        xf = xf.then(Xf.rotate(rot))
    xf = xf.then(Xf.translate(x, y))
    col = hex_rgb(COLORS.get(color, color)) if isinstance(color, str) else color
    if col is None and name in TINTABLE:
        col = hex_rgb(COLORS["red"])
    fn(c, xf, col, t)
