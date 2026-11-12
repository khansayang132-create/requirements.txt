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


# =====================================================================================
# Additions for the wider story formats (appended; nothing above this line was changed).
# Same style: basic shapes, a soft dark outline of the fill colour, one small highlight.
# =====================================================================================
def _c(name: str):
    return hex_rgb(COLORS.get(name, name))


def _eye(c, xf, x, y, r=7):
    c.ellipse(x, y, r, r * 1.15, INK, xf=xf)
    c.ellipse(x - r * 0.3, y - r * 0.35, r * 0.35, r * 0.35, WHITE, xf=xf)


# --------------------------------------------------------------------- animals -------
def p_bird(c, xf, col, t):
    col = _c("blue") if col is None else col
    o = _o(col)
    c.shape([(-60, 10), (-100, -18), (-96, 34)], darken(col, 0.12), o, 5, xf)
    c.ellipse(-6, 16, 64, 52, col, o, 6, xf)
    c.ellipse(-2, 34, 40, 28, lighten(col, 0.5), xf=xf)
    c.ellipse(-22, 12, 34, 22, darken(col, 0.14), o, 5, Xf.rotate(18 + 6 * math.sin(t * 5), -22, 12).then(xf))
    c.ellipse(44, -34, 38, 36, col, o, 6, xf)
    c.shape([(76, -40), (106, -30), (76, -18)], _c("orange"), darken(_c("orange"), 0.3), 4, xf)
    _eye(c, xf, 54, -42)
    for dx in (-14, 14):
        c.line([(dx, 64), (dx, 88), (dx + 14, 92)], _c("orange"), 6, xf)


def p_bee(c, xf, col, t):
    y = _c("yellow")
    flap = 0.7 + 0.3 * abs(math.sin(t * 12))
    for sx in (-1, 1):
        c.ellipse(sx * 26, -50 * flap, 30, 40 * flap, (226, 240, 255), (150, 190, 230), 4, Xf.rotate(sx * 24, sx * 26, -30).then(xf))
    c.ellipse(-6, 14, 70, 52, y, _o(y), 6, xf)
    for dx in (-30, 6):
        c.line([(dx, -32), (dx - 4, 14), (dx, 60)], INK, 15, xf, caps=False)
    c.ellipse(-6, 14, 70, 52, None, _o(y), 6, xf)
    c.ellipse(56, 4, 34, 34, y, _o(y), 6, xf)
    _eye(c, xf, 66, -4)
    c.line([(52, 16), (64, 22), (76, 16)], INK, 4, xf)
    c.line([(52, -28), (44, -60)], INK, 4, xf)
    c.line([(70, -26), (78, -58)], INK, 4, xf)
    c.shape([(-74, 6), (-98, 14), (-74, 24)], INK, xf=xf)


def p_cow(c, xf, col, t):
    w = hex_rgb("#FFF8EE")
    o = darken(w, 0.4)
    for sx in (-1, 1):
        c.ellipse(sx * 62, -44, 26, 16, w, o, 5, Xf.rotate(sx * 24, sx * 62, -44).then(xf))
        c.shape([(sx * 34, -70), (sx * 46, -98), (sx * 20, -78)], hex_rgb("#E9D8B4"), o, 4, xf)
    c.ellipse(0, -6, 62, 68, w, o, 6, xf)
    c.ellipse(-30, -36, 24, 28, INK, xf=xf)
    c.ellipse(34, 0, 16, 20, INK, xf=xf)
    c.ellipse(0, 44, 50, 34, _c("pink"), darken(_c("pink"), 0.3), 5, xf)
    for sx in (-1, 1):
        c.ellipse(sx * 18, 42, 7, 9, darken(_c("pink"), 0.4), xf=xf)
        _eye(c, xf, sx * 24, -18, 8)
    c.ellipse(0, -60, 20, 12, lighten(w, 0.5), xf=xf)


def p_sheep(c, xf, col, t):
    w = hex_rgb("#FDFBF5")
    o = darken(w, 0.3)
    for dx in (-36, 30):
        c.line([(dx, 44), (dx, 88)], INK, 13, xf)
    for cx, cy, r in ((-52, 6, 40), (-10, -24, 46), (34, -4, 42), (-20, 30, 44), (30, 32, 38), (-64, 30, 30)):
        c.ellipse(cx, cy, r + 5, r + 5, o, xf=xf)
    for cx, cy, r in ((-52, 6, 40), (-10, -24, 46), (34, -4, 42), (-20, 30, 44), (30, 32, 38), (-64, 30, 30)):
        c.ellipse(cx, cy, r, r, w, xf=xf)
    f = hex_rgb("#5B5470")
    c.ellipse(70, -16, 30, 34, f, darken(f, 0.3), 5, xf)
    c.ellipse(46, -40, 18, 10, f, darken(f, 0.3), 4, Xf.rotate(30, 46, -40).then(xf))
    c.ellipse(74, -22, 6, 7, WHITE, xf=xf)
    c.ellipse(76, -21, 3, 4, INK, xf=xf)
    c.ellipse(62, -52, 20, 16, w, o, 4, xf)


def p_pig(c, xf, col, t):
    p = hex_rgb("#FFB3C7")
    o = _o(p)
    for sx in (-1, 1):
        c.shape([(sx * 30, -66), (sx * 70, -86), (sx * 62, -40)], darken(p, 0.1), o, 5, xf)
    c.ellipse(0, 0, 80, 74, p, o, 6, xf)
    c.ellipse(0, 22, 36, 26, lighten(p, 0.25), o, 5, xf)
    for sx in (-1, 1):
        c.ellipse(sx * 13, 22, 6, 9, darken(p, 0.45), xf=xf)
        _eye(c, xf, sx * 30, -18, 8)
    c.line([(-20, 56), (0, 64), (20, 56)], darken(p, 0.45), 5, xf)
    c.ellipse(-44, 16, 12, 8, lighten(p, 0.35), xf=xf)


def p_owl(c, xf, col, t):
    b = hex_rgb("#B98A62")
    o = _o(b)
    for sx in (-1, 1):
        c.shape([(sx * 24, -74), (sx * 58, -100), (sx * 60, -56)], b, o, 5, xf)
    c.ellipse(0, 6, 70, 84, b, o, 6, xf)
    c.ellipse(0, 34, 44, 48, lighten(b, 0.5), xf=xf)
    for yy in (16, 36, 56):
        c.line([(-16, yy), (0, yy + 8), (16, yy)], darken(b, 0.1), 4, xf)
    blink = (t % 3.0) < 0.12
    for sx in (-1, 1):
        c.ellipse(sx * 28, -30, 27, 27, WHITE, o, 5, xf)
        if blink:
            c.line([(sx * 28 - 14, -30), (sx * 28 + 14, -30)], INK, 5, xf)
        else:
            c.ellipse(sx * 28, -30, 12, 13, INK, xf=xf)
            c.ellipse(sx * 28 - 4, -35, 4, 4, WHITE, xf=xf)
        c.ellipse(sx * 70, 20, 14, 40, darken(b, 0.16), o, 5, Xf.rotate(sx * -12, sx * 70, 20).then(xf))
    c.shape([(-9, -14), (9, -14), (0, 6)], _c("orange"), darken(_c("orange"), 0.3), 4, xf)
    for sx in (-1, 1):
        c.ellipse(sx * 20, 90, 16, 8, _c("orange"), darken(_c("orange"), 0.3), 4, xf)


def p_turtle(c, xf, col, t):
    g = hex_rgb("#7CCB7A")
    sh = hex_rgb("#4FA36A")
    for dx in (-48, 34):
        c.ellipse(dx, 60, 20, 22, g, _o(g), 5, xf)
    c.shape([(-80, 30), (-104, 44), (-80, 48)], g, _o(g), 4, xf)
    c.ellipse(76, 6, 30, 26, g, _o(g), 5, xf)
    _eye(c, xf, 84, -2, 6)
    c.line([(74, 16), (86, 20), (96, 14)], INK, 4, xf)
    dome = [(x, y) for x, y in ellipse_points(-6, 44, 82, 96, 48) if y <= 44]
    dome.sort(key=lambda q: q[0])
    c.shape(dome, sh, _o(sh), 6, xf)
    for dx, dy, r in ((-40, 10, 17), (-6, -20, 19), (30, 10, 17), (-6, 22, 12)):
        c.ellipse(dx, dy, r, r * 0.8, lighten(sh, 0.3), darken(sh, 0.2), 4, xf)


def p_chick(c, xf, col, t):
    y = hex_rgb("#FFE066")
    o = _o(y)
    c.ellipse(0, 28, 60, 54, y, o, 6, xf)
    c.ellipse(-44, 26, 20, 28, darken(y, 0.08), o, 5, Xf.rotate(-20 + 8 * math.sin(t * 6), -44, 26).then(xf))
    c.ellipse(16, -40, 42, 40, y, o, 6, xf)
    for rot in (-20, 0, 20):
        c.ellipse(16, -88, 6, 14, y, o, 4, Xf.rotate(rot, 16, -74).then(xf))
    c.shape([(50, -42), (78, -34), (50, -24)], _c("orange"), darken(_c("orange"), 0.3), 4, xf)
    _eye(c, xf, 30, -48)
    for dx in (-14, 14):
        c.line([(dx, 78), (dx, 94), (dx + 12, 96)], _c("orange"), 6, xf)


def p_caterpillar(c, xf, col, t):
    g = hex_rgb("#7BD46B")
    for i, dx in enumerate((-78, -44, -10, 24)):
        yy = 30 + 10 * math.sin(t * 4 + i * 1.2)
        c.ellipse(dx, yy, 26, 26, g if i % 2 else lighten(g, 0.2), _o(g), 5, xf)
        c.line([(dx, yy + 24), (dx, yy + 38)], INK, 5, xf)
    c.ellipse(64, 6, 34, 34, lighten(g, 0.12), _o(g), 6, xf)
    _eye(c, xf, 72, 0)
    c.line([(58, 18), (70, 24), (82, 18)], INK, 4, xf)
    c.line([(56, -24), (48, -56)], INK, 4, xf)
    c.line([(74, -24), (84, -54)], INK, 4, xf)
    c.ellipse(48, -58, 6, 6, _c("yellow"), xf=xf)
    c.ellipse(84, -56, 6, 6, _c("yellow"), xf=xf)


def p_cocoon(c, xf, col, t):
    b = hex_rgb("#B6C97A")
    sw = Xf.rotate(4 * math.sin(t * 1.6), 0, -92).then(xf)
    c.line([(-60, -92), (60, -92)], hex_rgb("#9B6B43"), 14, xf)
    c.line([(0, -92), (0, -62)], darken(b, 0.4), 6, sw)
    c.ellipse(0, 6, 40, 72, b, _o(b), 6, sw)
    for yy in (-30, -4, 22, 48):
        c.line([(-32, yy), (0, yy + 10), (32, yy)], darken(b, 0.18), 5, sw)
    c.ellipse(-14, -26, 8, 16, lighten(b, 0.4), xf=sw)


def p_tadpole(c, xf, col, t):
    g = hex_rgb("#5F8F6B")
    wag = math.sin(t * 7) * 16
    c.line([(-20, 6), (-56, 6 + wag * 0.5), (-98, 6 + wag)], _o(g), 20, xf)
    c.line([(-20, 6), (-56, 6 + wag * 0.5), (-98, 6 + wag)], g, 11, xf)
    c.ellipse(26, 4, 52, 44, g, _o(g), 6, xf)
    c.ellipse(46, -8, 11, 12, WHITE, xf=xf)
    c.ellipse(49, -7, 6, 7, INK, xf=xf)
    c.line([(40, 18), (52, 22), (62, 16)], INK, 4, xf)


def p_worm(c, xf, col, t):
    p = hex_rgb("#F2A6B8")
    w = math.sin(t * 3) * 8
    pts = [(-90, 40), (-56, 10 - w), (-20, 40), (16, 10 + w), (50, 36), (78, -10)]
    c.line(pts, _o(p), 34, xf)
    c.line(pts, p, 24, xf)
    c.ellipse(78, -14, 24, 24, p, _o(p), 5, xf)
    _eye(c, xf, 84, -20, 6)
    c.line([(72, -4), (82, 0), (92, -6)], INK, 4, xf)


# --------------------------------------------------------------------- nature --------
def p_snowflake(c, xf, col, t):
    w = hex_rgb("#E8F6FF")
    o = hex_rgb("#7FB8E6")
    R = Xf.rotate(t * 10).then(xf)
    for i in range(6):
        A = Xf.rotate(i * 60).then(R)
        for col_, wd in ((o, 16), (w, 8)):
            c.line([(0, 0), (0, -90)], col_, wd, A)
            c.line([(0, -52), (-24, -76)], col_, wd, A)
            c.line([(0, -52), (24, -76)], col_, wd, A)
    c.ellipse(0, 0, 14, 14, w, o, 4, xf)


def p_feather(c, xf, col, t):
    col = hex_rgb("#8ED1F2") if col is None else col
    R = Xf.rotate(24 + 5 * math.sin(t * 1.5)).then(xf)
    c.ellipse(0, -14, 36, 82, col, _o(col), 6, R)
    c.line([(0, -92), (0, 96)], WHITE, 6, R)
    for yy in (-50, -20, 10, 40):
        c.line([(0, yy), (26, yy - 20)], lighten(col, 0.5), 4, R)
        c.line([(0, yy), (-26, yy - 20)], lighten(col, 0.5), 4, R)


def p_rock(c, xf, col, t):
    g = hex_rgb("#A9A9B8")
    c.shape([(-90, 60), (-70, -10), (-24, -56), (40, -50), (86, 0), (92, 60)], g, _o(g), 6, xf)
    c.line([(-40, -20), (-14, -36)], lighten(g, 0.45), 10, xf)
    c.line([(20, 20), (50, 34)], darken(g, 0.15), 6, xf)


def p_shell(c, xf, col, t):
    s = hex_rgb("#FFD3B0")
    fan = [(x, y) for x, y in ellipse_points(0, 50, 92, 120, 48) if y <= 50]
    fan.sort(key=lambda q: q[0])
    c.shape([(-26, 78), (26, 78), (40, 50), (-40, 50)], darken(s, 0.1), _o(s), 6, xf)
    c.shape(fan + [(0, 62)], s, _o(s), 6, xf)
    for a in (-56, -28, 0, 28, 56):
        r = math.radians(a - 90)
        c.line([(0, 50), (84 * math.cos(r), 50 + 108 * math.sin(r))], darken(s, 0.22), 5, xf)


def p_pinecone(c, xf, col, t):
    b = hex_rgb("#9B6B43")
    c.ellipse(0, 6, 56, 80, b, _o(b), 6, xf)
    for row, yy in enumerate((-48, -20, 8, 36, 62)):
        n = (2, 3, 4, 3, 2)[row]
        for i in range(n):
            xx = (i - (n - 1) / 2) * 28
            c.shape([(xx - 15, yy - 10), (xx + 15, yy - 10), (xx, yy + 14)], lighten(b, 0.25), darken(b, 0.3), 3, xf)
    c.line([(0, -76), (0, -94)], darken(b, 0.4), 9, xf)


# ----------------------------------------------------------------- home & clothes ----
def p_spoon(c, xf, col, t):
    s = hex_rgb("#C9D3E0")
    R = Xf.rotate(20).then(xf)
    c.line([(0, -10), (0, 92)], _o(s), 22, R)
    c.line([(0, -10), (0, 92)], s, 12, R)
    c.ellipse(0, -50, 34, 46, s, _o(s), 6, R)
    c.ellipse(-8, -60, 10, 18, lighten(s, 0.6), xf=R)


def p_bowl(c, xf, col, t):
    col = _c("blue") if col is None else col
    bowl = [(x, y) for x, y in ellipse_points(0, -10, 94, 92, 48) if y >= -10]
    bowl.sort(key=lambda q: -q[0])
    c.shape(bowl, col, _o(col), 6, xf)
    c.ellipse(0, -10, 94, 20, lighten(col, 0.5), _o(col), 6, xf)
    c.shape([(-40, 72), (40, 72), (46, 88), (-46, 88)], darken(col, 0.12), _o(col), 5, xf)
    c.line([(-66, 20), (-50, 44)], lighten(col, 0.4), 9, xf)


def p_shoe(c, xf, col, t):
    col = _c("red") if col is None else col
    c.shape([(-80, 60), (-80, -50), (-20, -50), (-10, 0), (60, 14), (90, 40), (90, 60)], col, _o(col), 6, xf)
    c.shape([(-86, 60), (94, 60), (94, 80), (-86, 80)], WHITE, (170, 170, 190), 5, xf)
    for dx in (0, 22, 44):
        c.line([(dx - 14, 6 + dx * 0.25), (dx, 28 + dx * 0.25)], WHITE, 6, xf)
    c.line([(-74, -40), (-26, -40)], lighten(col, 0.5), 9, xf)


def p_boot(c, xf, col, t):
    col = _c("yellow") if col is None else col
    c.shape([(-50, -90), (22, -90), (22, 10), (86, 34), (90, 70), (-50, 70)], col, _o(col), 6, xf)
    c.shape([(-56, 66), (94, 66), (94, 86), (-56, 86)], darken(col, 0.2), _o(col), 5, xf)
    c.shape([(-50, -90), (22, -90), (22, -64), (-50, -64)], lighten(col, 0.4), _o(col), 5, xf)


def p_mitten(c, xf, col, t):
    col = _c("red") if col is None else col
    c.ellipse(-58, 4, 22, 34, col, _o(col), 6, Xf.rotate(-28, -58, 4).then(xf))
    body = [(x, y) for x, y in ellipse_points(4, -10, 56, 82, 40) if y <= 30]
    body.sort(key=lambda q: q[0])
    c.shape([(-52, 60)] + body + [(60, 60)], col, _o(col), 6, xf)
    c.shape([(-56, 56), (64, 56), (64, 90), (-56, 90)], lighten(col, 0.55), _o(col), 5, xf)
    c.shape(star_points(4, -6, 24, 11), lighten(col, 0.6), xf=xf)


def p_scarf(c, xf, col, t):
    col = _c("green") if col is None else col
    c.shape([(20, -30), (64, -30), (70, 84), (26, 84)], col, _o(col), 6, xf)
    for dx in (32, 46, 60):
        c.line([(dx, 84), (dx, 100)], _o(col), 5, xf)
    c.ellipse(0, -40, 86, 30, col, _o(col), 6, xf)
    c.ellipse(0, -46, 54, 12, darken(col, 0.3), xf=xf)
    for dx in (-54, -18, 44):
        c.line([(dx, -64 + abs(dx) * 0.12), (dx + 8, -18 - abs(dx) * 0.05)], lighten(col, 0.55), 10, xf, caps=False)
    for yy in (4, 44):
        c.line([(23, yy), (67, yy)], lighten(col, 0.55), 10, xf, caps=False)


def p_basket(c, xf, col, t):
    b = hex_rgb("#D9A066")
    arc = [(x, y) for x, y in ellipse_points(0, -6, 70, 86, 40) if y <= -6]
    arc.sort(key=lambda q: q[0])
    c.line(arc, _o(b), 14, xf)
    c.line(arc, b, 7, xf)
    c.shape([(-84, -6), (84, -6), (62, 84), (-62, 84)], b, _o(b), 6, xf)
    for yy in (18, 42, 66):
        c.line([(-74 + (yy * 0.22), yy), (74 - (yy * 0.22), yy)], darken(b, 0.2), 5, xf)
    for dx in (-40, 0, 40):
        c.line([(dx, 0), (dx * 0.8, 80)], darken(b, 0.2), 5, xf)
    c.shape([(-90, -16), (90, -16), (90, 6), (-90, 6)], lighten(b, 0.2), _o(b), 5, xf)


def p_broom(c, xf, col, t):
    R = Xf.rotate(-14).then(xf)
    c.line([(0, -96), (0, 20)], darken("#B07A4F", 0.3), 14, R)
    c.line([(0, -96), (0, 20)], hex_rgb("#B07A4F"), 8, R)
    s = hex_rgb("#F2C94C")
    c.shape([(-30, 14), (30, 14), (56, 92), (-56, 92)], s, _o(s), 6, R)
    for dx in (-30, -10, 10, 30):
        c.line([(dx * 0.5, 34), (dx, 86)], darken(s, 0.25), 4, R)
    c.shape([(-32, 8), (32, 8), (32, 28), (-32, 28)], _c("red"), darken(_c("red"), 0.3), 5, R)


def p_clock(c, xf, col, t):
    col = _c("blue") if col is None else col
    c.ellipse(0, 0, 90, 90, col, _o(col), 6, xf, n=56)
    c.ellipse(0, 0, 70, 70, WHITE, _o(col), 5, xf, n=56)
    for i in range(12):
        a = math.radians(i * 30)
        c.ellipse(58 * math.cos(a), 58 * math.sin(a), 4 if i % 3 else 7, 4 if i % 3 else 7, INK, xf=xf)
    c.line([(0, 0), (0, -44)], INK, 8, xf)
    c.line([(0, 0), (30, 12)], INK, 8, xf)
    c.ellipse(0, 0, 8, 8, _c("red"), xf=xf)


def p_wateringcan(c, xf, col, t):
    col = _c("green") if col is None else col
    c.line([(40, 20), (92, -40)], _o(col), 22, xf)
    c.line([(40, 20), (92, -40)], col, 12, xf)
    c.ellipse(96, -46, 20, 12, lighten(col, 0.3), _o(col), 5, Xf.rotate(-50, 96, -46).then(xf))
    c.ellipse(-70, 16, 30, 40, None, _o(col), 12, xf)
    c.shape([(-60, -40), (50, -40), (56, 84), (-66, 84)], col, _o(col), 6, xf)
    c.ellipse(-5, -40, 55, 14, lighten(col, 0.35), _o(col), 5, xf)
    c.line([(-40, -10), (-40, 50)], lighten(col, 0.45), 10, xf)


def p_quilt(c, xf, col, t):
    cols = ["pink", "yellow", "blue", "green", "purple", "orange", "blue", "pink", "yellow"]
    for i in range(9):
        x0, y0 = -84 + (i % 3) * 56, -84 + (i // 3) * 56
        k = _c(cols[i])
        c.shape([(x0, y0), (x0 + 56, y0), (x0 + 56, y0 + 56), (x0, y0 + 56)], k, darken(k, 0.3), 4, xf)
        c.shape(star_points(x0 + 28, y0 + 30, 13, 6), lighten(k, 0.6), xf=xf)
    c.shape([(-84, -84), (84, -84), (84, 84), (-84, 84)], None, INK, 6, xf)


def p_vase(c, xf, col, t):
    col = _c("blue") if col is None else col
    g = hex_rgb("#4CAF50")
    for dx, cc in ((-26, "pink"), (0, "yellow"), (26, "red")):
        c.line([(dx * 0.4, -20), (dx, -70)], g, 7, xf)
        c.ellipse(dx, -78, 17, 17, _c(cc), darken(_c(cc), 0.3), 4, xf)
        c.ellipse(dx, -78, 6, 6, hex_rgb("#FFF6E3"), xf=xf)
    c.shape([(-26, -24), (26, -24), (20, 0), (52, 40), (40, 90), (-40, 90), (-52, 40), (-20, 0)], col, _o(col), 6, xf)
    c.line([(-30, 34), (-24, 66)], lighten(col, 0.5), 9, xf)


def p_xylophone(c, xf, col, t):
    c.shape([(-96, 30), (96, 4), (96, 30), (-96, 62)], hex_rgb("#B07A4F"), darken("#B07A4F", 0.3), 5, xf)
    for i, cc in enumerate(("red", "orange", "yellow", "green", "blue", "purple")):
        x = -80 + i * 32
        h = 70 - i * 7
        k = _c(cc)
        c.shape([(x - 12, 40 - i * 4.5 - h), (x + 12, 40 - i * 4.5 - h), (x + 12, 44 - i * 4.5), (x - 12, 44 - i * 4.5)], k, _o(k), 4, xf)
    c.line([(30, -90), (-10, -50)], hex_rgb("#8A6A4A"), 7, xf)
    c.ellipse(-12, -48, 11, 11, _c("pink"), darken(_c("pink"), 0.3), 4, xf)


def p_yarn(c, xf, col, t):
    col = _c("pink") if col is None else col
    c.line([(40, 60), (70, 84), (100, 70)], _o(col), 9, xf)
    c.line([(40, 60), (70, 84), (100, 70)], col, 5, xf)
    c.ellipse(0, 0, 80, 80, col, _o(col), 6, xf, n=48)
    for rot in (-40, -10, 24, 60):
        c.ellipse(0, 0, 78, 30, None, darken(col, 0.2), 5, Xf.rotate(rot).then(xf))
    c.ellipse(0, 0, 80, 80, None, _o(col), 6, xf, n=48)
    c.ellipse(-30, -34, 12, 9, lighten(col, 0.55), xf=xf)


def p_zipper(c, xf, col, t):
    col = _c("purple") if col is None else col
    c.shape([(-60, -94), (-8, -94), (-8, 94), (-60, 94)], col, _o(col), 6, xf)
    c.shape([(8, -94), (60, -94), (60, 94), (8, 94)], col, _o(col), 6, xf)
    s = hex_rgb("#C9D3E0")
    for i in range(9):
        yy = -80 + i * 20
        c.line([(-14 if i % 2 else 0, yy), (0 if i % 2 else 14, yy)], darken(s, 0.3), 9, xf, caps=False)
    c.shape([(-18, -40), (18, -40), (12, -8), (-12, -8)], s, _o(s), 5, xf)
    c.shape([(-9, -8), (9, -8), (9, 30), (-9, 30)], s, _o(s), 5, xf)


# ------------------------------------------------------------------------ food -------
def p_grapes(c, xf, col, t):
    p = _c("purple")
    c.line([(0, -60), (6, -92)], hex_rgb("#8A5A3A"), 8, xf)
    lf = hex_rgb("#58B368")
    c.ellipse(30, -78, 28, 13, lf, _o(lf), 4, Xf.rotate(-20, 30, -78).then(xf))
    for row, n in enumerate((3, 4, 3, 2, 1)):
        for i in range(n):
            x, y = (i - (n - 1) / 2) * 38, -40 + row * 32
            c.ellipse(x, y, 22, 22, p, _o(p), 4, xf)
            c.ellipse(x - 7, y - 8, 6, 5, lighten(p, 0.5), xf=xf)


def p_strawberry(c, xf, col, t):
    r = _c("red")
    c.shape([(-64, -40), (-40, -64), (40, -64), (64, -40), (40, 40), (0, 92), (-40, 40)], r, _o(r), 6, xf)
    for dx, dy in ((-28, -24), (10, -30), (34, -4), (-10, 6), (14, 36), (-24, 34), (0, 62)):
        c.ellipse(dx, dy, 4, 6, hex_rgb("#FFE9A8"), xf=xf)
    g = hex_rgb("#58B368")
    for rot in (-60, -20, 20, 60):
        c.ellipse(0, -84, 12, 28, g, _o(g), 4, Xf.rotate(rot, 0, -62).then(xf))


def p_pear(c, xf, col, t):
    g = hex_rgb("#C5DC5A")
    c.line([(0, -70), (8, -96)], hex_rgb("#8A5A3A"), 9, xf)
    c.ellipse(0, -36, 36, 44, g, _o(g), 6, xf)
    c.ellipse(0, 30, 60, 62, g, _o(g), 6, xf)
    c.ellipse(0, -14, 33, 40, g, xf=xf)
    c.ellipse(-24, 14, 10, 20, lighten(g, 0.5), xf=Xf.rotate(14, -24, 14).then(xf))


def p_bread(c, xf, col, t):
    b = hex_rgb("#E2A861")
    top = [(x, y) for x, y in ellipse_points(0, -10, 94, 62, 40) if y <= -10]
    top.sort(key=lambda q: q[0])
    c.shape(top + [(84, 70), (-84, 70)], b, _o(b), 6, xf)
    for dx in (-44, 0, 44):
        c.line([(dx - 12, -44), (dx + 12, -14)], lighten(b, 0.45), 9, xf)
    c.line([(-70, 44), (70, 44)], darken(b, 0.12), 6, xf)


def p_milk(c, xf, col, t):
    g = hex_rgb("#DDF2FF")
    c.shape([(-52, -84), (52, -84), (44, 88), (-44, 88)], g, darken(g, 0.35), 6, xf)
    c.shape([(-49, -30), (49, -30), (44, 88), (-44, 88)], WHITE, xf=xf)
    c.ellipse(0, -30, 49, 10, WHITE, (200, 215, 230), 4, xf)
    c.shape([(-52, -84), (52, -84), (44, 88), (-44, 88)], None, darken(g, 0.35), 6, xf)
    c.line([(-30, -66), (-26, 40)], lighten(g, 0.7), 8, xf)


PROPS.update({
    "bird": p_bird, "bee": p_bee, "cow": p_cow, "sheep": p_sheep, "pig": p_pig, "owl": p_owl, "turtle": p_turtle,
    "chick": p_chick, "caterpillar": p_caterpillar, "cocoon": p_cocoon, "tadpole": p_tadpole, "worm": p_worm,
    "snowflake": p_snowflake, "feather": p_feather, "rock": p_rock, "shell": p_shell, "pinecone": p_pinecone,
    "spoon": p_spoon, "bowl": p_bowl, "shoe": p_shoe, "boot": p_boot, "mitten": p_mitten, "scarf": p_scarf,
    "basket": p_basket, "broom": p_broom, "clock": p_clock, "wateringcan": p_wateringcan, "quilt": p_quilt,
    "vase": p_vase, "xylophone": p_xylophone, "yarn": p_yarn, "zipper": p_zipper, "grapes": p_grapes,
    "strawberry": p_strawberry, "pear": p_pear, "bread": p_bread, "milk": p_milk,
})
TINTABLE.update({"bird", "feather", "bowl", "shoe", "boot", "mitten", "scarf", "clock", "wateringcan", "vase", "yarn", "zipper"})
SPOKEN.update({"wateringcan": "watering can", "pinecone": "pine cone"})
PLURAL.update({"sheep": "sheep", "strawberry": "strawberries", "wateringcan": "watering cans", "pinecone": "pine cones",
               "milk": "glasses of milk", "bread": "loaves of bread", "grapes": "grapes", "yarn": "balls of yarn",
               "scarf": "scarves"})
for _letter, _words in {"B": ["bird", "bee", "basket", "bowl", "boot", "broom", "bread"], "C": ["cow", "chick", "caterpillar", "clock"],
                        "F": ["feather"], "G": ["grapes"], "M": ["mitten", "milk"], "O": ["owl"], "P": ["pig", "pear", "pinecone"],
                        "Q": ["quilt"], "R": ["rock"], "S": ["sheep", "shell", "spoon", "shoe", "scarf", "snowflake", "strawberry"],
                        "T": ["turtle", "tadpole"], "V": ["vase"], "W": ["worm", "wateringcan"], "X": ["xylophone"], "Y": ["yarn"],
                        "Z": ["zipper"]}.items():
    LETTERS.setdefault(_letter, []).extend(_words)
del _letter, _words
