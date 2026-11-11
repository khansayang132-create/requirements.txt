"""The character rig: one parametric puppet shared by all Wonder Meadow characters.

A character is drawn from the bible entry (species, colours, accessory) plus a ``Pose``.
Local space: origin at the middle of the feet, y grows downward (so the head is at
negative y), one unit = one output pixel at scale 1.0. All species share the body,
arms, eyes and mouth; ears, muzzle, trunk, beak, tail and accessory are per species.
Because every episode draws from this one function, the characters cannot drift
between episodes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .canvas import Canvas, Xf, darken, ellipse_points, hex_rgb, lighten, mix

INK = (59, 51, 85)
MOUTH_DARK = (122, 46, 59)
TONGUE = (255, 138, 150)
WHITE = (255, 255, 255)


@dataclass
class Pose:
    x: float = 540.0
    y: float = 1250.0
    scale: float = 1.0
    flip: bool = False
    squash: float = 0.0      # >0 squashed (landing), <0 stretched (jumping)
    lift: float = 0.0        # pixels above the ground
    head_tilt: float = 0.0   # degrees
    arm_l: float = 18.0      # degrees from hanging down, outward/up positive (screen-left arm)
    arm_r: float = 18.0
    look: float = 0.0        # -1..1
    look_y: float = 0.0
    blink: float = 0.0       # 0 open .. 1 closed
    mouth: float = 0.0       # 0 closed smile .. 1 wide open
    mood: str = "happy"      # happy | wow | sleepy | asleep | sad
    ear: float = 0.0         # ear / tail wiggle in degrees
    step: float = 0.0        # walk phase in radians
    lean: float = 0.0        # whole-body lean in degrees

    def with_(self, **kw) -> "Pose":
        return replace(self, **kw)


SHOULDER = (92.0, -182.0)
ARM_LEN = 96.0
HEAD_PIVOT = (0.0, -212.0)


def body_xf(p: Pose) -> Xf:
    sx = p.scale * (1 + p.squash * 0.45)
    sy = p.scale * (1 - p.squash * 0.45)
    xf = Xf.scale(-sx if p.flip else sx, sy)
    if p.lean:
        xf = xf.then(Xf.rotate(p.lean))
    return xf.then(Xf.translate(p.x, p.y - p.lift))


def head_xf(p: Pose) -> Xf:
    return Xf.rotate(p.head_tilt, *HEAD_PIVOT).then(body_xf(p))


def hand_pos(p: Pose, side: int) -> tuple[float, float]:
    """Canvas position of a hand. side: -1 = the character's screen-left arm, +1 = right."""
    ang = math.radians(p.arm_l if side < 0 else p.arm_r)
    lx = side * SHOULDER[0] + side * ARM_LEN * math.sin(ang)
    ly = SHOULDER[1] + ARM_LEN * math.cos(ang)
    return body_xf(p).pt(lx, ly)


def head_top(p: Pose) -> tuple[float, float]:
    return head_xf(p).pt(0, -450)


def _arm(c: Canvas, xf: Xf, side: int, angle: float, col, out, duck: bool) -> None:
    ang = math.radians(angle)
    sx, sy = side * SHOULDER[0], SHOULDER[1]
    ex, ey = sx + side * ARM_LEN * math.sin(ang), sy + ARM_LEN * math.cos(ang)
    if duck:
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        rot = Xf.rotate(-side * angle, mx, my).then(xf)
        c.ellipse(mx, my, 30, 62, col, out, 5, rot)
    else:
        c.capsule(sx, sy, ex, ey, 46, col, out, 5, xf)


def _eye(c: Canvas, xf: Xf, ex: float, ey: float, p: Pose, r: float = 1.0) -> None:
    if p.mood == "asleep":
        pts = [(ex - 24 * r, ey - 2), (ex - 12 * r, ey + 9), (ex, ey + 12), (ex + 12 * r, ey + 9), (ex + 24 * r, ey - 2)]
        c.line(pts, INK, 7, xf)
        return
    if p.blink >= 0.5:
        pts = [(ex - 24 * r, ey + 6), (ex - 12 * r, ey - 6), (ex, ey - 9), (ex + 12 * r, ey - 6), (ex + 24 * r, ey + 6)]
        c.line(pts, INK, 7, xf)
        return
    grow = 1.14 if p.mood == "wow" else 1.0
    rx, ry = 31 * r * grow, 35 * r * grow
    c.ellipse(ex, ey, rx, ry, WHITE, INK, 4, xf, n=40)
    px, py = ex + p.look * 9, ey + p.look_y * 7 + (4 if p.mood == "sad" else 0)
    c.ellipse(px, py, 18 * r * grow, 21 * r * grow, INK, xf=xf, n=32)
    c.ellipse(px - 6, py - 8, 7 * r, 7 * r, WHITE, xf=xf, n=16)
    c.ellipse(px + 7, py + 8, 3.5 * r, 3.5 * r, (210, 210, 230), xf=xf, n=12)
    if p.mood == "sleepy":
        cut = ey - ry * 0.28
        lid = [(x, y) for x, y in ellipse_points(ex, ey, rx + 4, ry + 4, 40) if y <= cut]
        lid.sort(key=lambda q: q[0])
        if len(lid) >= 3:
            c.shape(lid, c._lid_color, xf=xf)
            c.line([(ex - rx * 0.93, cut + 3), (ex, cut - 5), (ex + rx * 0.93, cut + 3)], darken(c._lid_color, 0.42), 5, xf)


def _mouth(c: Canvas, xf: Xf, mx: float, my: float, p: Pose, teeth: bool = False) -> None:
    m = p.mouth
    if m < 0.12:
        if p.mood == "sad":
            pts = [(mx - 20, my + 6), (mx - 10, my - 2), (mx, my - 4), (mx + 10, my - 2), (mx + 20, my + 6)]
        elif p.mood == "wow":
            c.ellipse(mx, my + 2, 11, 13, MOUTH_DARK, INK, 3, xf, n=20)
            return
        else:
            pts = [(mx - 24, my - 8), (mx - 12, my + 3), (mx, my + 7), (mx + 12, my + 3), (mx + 24, my - 8)]
        c.line(pts, INK, 6, xf)
        if teeth and p.mood not in ("sad",):
            c.rrect_xf([(mx - 11, my + 5), (mx - 1, my + 5), (mx - 1, my + 20), (mx - 11, my + 20)], WHITE, INK, 2.5, xf)
            c.rrect_xf([(mx + 1, my + 5), (mx + 11, my + 5), (mx + 11, my + 20), (mx + 1, my + 20)], WHITE, INK, 2.5, xf)
        return
    rx, ry = 18 + 7 * m, 5 + 17 * m
    c.ellipse(mx, my + ry * 0.45, rx, ry, MOUTH_DARK, INK, 4, xf, n=28)
    if m > 0.35:
        tongue = [(x, y) for x, y in ellipse_points(mx, my + ry * 1.05, rx * 0.72, ry * 0.55, 24) if y <= my + ry * 1.38]
        if len(tongue) >= 3:
            c.shape(tongue, TONGUE, xf=xf)


def _rrect_xf(self: Canvas, pts, fill, outline, width, xf: Xf) -> None:
    self.shape(pts, fill, outline, width, xf)


Canvas.rrect_xf = _rrect_xf  # small quad helper used for teeth
Canvas._lid_color = (0, 0, 0)


def draw_character(c: Canvas, spec: dict, p: Pose, shadow_color=None) -> None:
    """Draw one character. ``spec`` is its entry from config/universe.yaml."""
    species = spec["species"]
    col = spec["colors"]
    body = hex_rgb(col["body"])
    belly = hex_rgb(col["belly"])
    inner = hex_rgb(col["inner_ear"])
    accent = hex_rgb(col["accent"])
    nose = hex_rgb(col["nose"])
    out = darken(body, 0.36)
    acc_out = darken(accent, 0.3)
    accessory = spec.get("clothing", {}).get("accessory")
    c._lid_color = body

    T = body_xf(p)
    H = head_xf(p)
    s = p.scale

    if shadow_color is not None:
        k = max(0.45, 1 - p.lift / 320)
        c.ellipse(p.x, p.y + 8 * s, 128 * s * k, 24 * s * k, shadow_color, n=40)

    wig = p.ear

    # ---- tail (behind everything)
    if species == "bunny":
        c.ellipse(-98, -72, 34, 32, lighten(belly, 0.3), out, 4, T)
    elif species == "cat":
        sway = wig * 1.6
        tail = [(-88, -58), (-150, -70 - sway * 0.3), (-186, -120 - sway * 0.6), (-184, -180 - sway), (-158, -222 - sway)]
        c.line(tail, out, 44, T)
        c.line(tail, body, 34, T)
        stripe = hex_rgb(col.get("stripe", darken(body, 0.15)))
        for a, b in ((1, 2), (2, 3), (3, 4)):
            mx, my = (tail[a][0] + tail[b][0]) / 2, (tail[a][1] + tail[b][1]) / 2
            c.line([(mx - 14, my - 3), (mx + 14, my + 3)], stripe, 9, T)
    elif species == "elephant":
        c.line([(-100, -90), (-140, -70), (-150, -40)], out, 12, T)
        c.ellipse(-150, -34, 12, 14, out, xf=T)
    elif species == "bear":
        c.ellipse(-100, -74, 24, 23, body, out, 4, T)
    elif species == "duck":
        c.shape([(-80, -120), (-150, -150), (-96, -70)], body, out, 5, T)

    # ---- ears behind the head
    if species == "bunny":
        for side in (-1, 1):
            E = Xf.rotate(side * (7 + wig), side * 62, -400).then(H)
            c.ellipse(side * 62, -505, 41, 122, body, out, 5, E)
            c.ellipse(side * 62, -500, 20, 90, inner, xf=E)
    elif species == "cat":
        for side in (-1, 1):
            E = Xf.rotate(side * wig * 0.5, side * 100, -400).then(H)
            c.shape([(side * 146, -372), (side * 126, -492), (side * 44, -426)], body, out, 5, E)
            c.shape([(side * 128, -392), (side * 118, -458), (side * 72, -420)], inner, xf=E)
    elif species == "elephant":
        for side in (-1, 1):
            E = Xf.rotate(side * (6 + wig * 1.4), side * 118, -318).then(H)
            c.ellipse(side * 180, -322, 100, 116, body, out, 5, E)
            c.ellipse(side * 176, -316, 66, 82, inner, xf=E)
    elif species == "bear":
        for side in (-1, 1):
            c.ellipse(side * 114, -414, 52, 50, body, out, 5, H)
            c.ellipse(side * 114, -412, 29, 27, inner, xf=H)

    # ---- feet
    foot_col = accent if accessory == "boots" else (hex_rgb(col["nose"]) if species == "duck" else darken(body, 0.12))
    foot_out = darken(foot_col, 0.32)
    for side in (-1, 1):
        up = max(0.0, math.sin(p.step + (0 if side < 0 else math.pi))) * 16
        if accessory == "boots":
            c.capsule(side * 52, -52 - up, side * 52, -18 - up, 50, foot_col, foot_out, 4, T)
            c.ellipse(side * 60, -16 - up, 44, 24, foot_col, foot_out, 4, T)
            c.line([(side * 30, -62 - up), (side * 74, -62 - up)], lighten(foot_col, 0.35), 10, T)
        else:
            c.ellipse(side * 54, -16 - up, 48, 27, foot_col, foot_out, 5, T)

    # ---- body, belly, clothing
    body_pts = ellipse_points(0, -120, 110, 114, 56)
    c.shape(body_pts, body, out, 5, T)
    c.ellipse(0, -106, 70, 76, belly, xf=T)
    if accessory == "overalls":
        lower = [(x, y) for x, y in body_pts if y >= -112]
        lower.sort(key=lambda q: math.atan2(q[1] + 120, q[0]))
        c.shape(lower, accent, acc_out, 5, T)
        for side in (-1, 1):
            c.line([(side * 60, -116), (side * 50, -196)], accent, 20, T)
            c.ellipse(side * 58, -118, 9, 9, hex_rgb("#FFD95A"), acc_out, 2, T)
        c.rrect_xf([(-30, -100), (30, -100), (26, -58), (-26, -58)], lighten(accent, 0.18), acc_out, 3, T)

    # ---- arms
    _arm(c, T, -1, p.arm_l, body, out, species == "duck")
    _arm(c, T, 1, p.arm_r, body, out, species == "duck")

    # ---- neck accessories (under the head)
    if accessory == "scarf":
        c.shape([(38, -214), (78, -206), (92, -122), (54, -116)], accent, acc_out, 4, T)
        c.line([(60, -150), (82, -146)], lighten(accent, 0.4), 6, T)
    elif accessory == "bandana":
        c.shape([(-78, -212), (78, -212), (0, -128)], accent, acc_out, 4, T)
        for dx, dy in ((-24, -188), (22, -186), (0, -160)):
            c.ellipse(dx, dy, 6, 6, lighten(accent, 0.55), xf=T)

    # ---- head
    c.ellipse(0, -308, 154, 138, body, out, 5, H, n=64)
    if accessory == "scarf":
        c.ellipse(0, -202, 92, 27, accent, acc_out, 4, T)

    eye_y, eye_dx, mouth_y = -304, 62, -244
    if species in ("bunny", "cat"):
        c.ellipse(0, -254, 60, 42, lighten(belly, 0.2), xf=H)
    elif species == "bear":
        c.ellipse(0, -256, 68, 52, belly, xf=H)
        mouth_y = -240
    elif species == "duck":
        eye_y, eye_dx = -316, 54
    elif species == "elephant":
        eye_y, eye_dx = -318, 66

    # cheeks
    blush = mix(body, (255, 120, 150), 0.5)
    for side in (-1, 1):
        c.ellipse(side * (eye_dx + 46), eye_y + 46, 26, 16, blush, xf=H)

    _eye(c, H, -eye_dx, eye_y, p)
    _eye(c, H, eye_dx, eye_y, p)

    if species == "bunny":
        _mouth(c, H, 0, mouth_y, p, teeth=True)
        c.ellipse(0, -266, 13, 10, nose, darken(nose, 0.3), 3, H)
    elif species == "cat":
        for side in (-1, 1):
            for dy in (-14, 0, 14):
                c.line([(side * 72, -258 + dy * 0.4), (side * 138, -262 + dy)], darken(body, 0.45), 3.5, H)
        _mouth(c, H, 0, mouth_y, p)
        c.shape([(-13, -274), (13, -274), (0, -258)], nose, darken(nose, 0.3), 3, H)
        stripe = hex_rgb(col.get("stripe", darken(body, 0.15)))
        for dx, top in ((-26, -430), (0, -438), (26, -430)):
            c.line([(dx, top), (dx * 0.8, top + 34)], stripe, 11, H)
    elif species == "bear":
        _mouth(c, H, 0, mouth_y, p)
        c.ellipse(0, -276, 21, 15, nose, xf=H)
        c.ellipse(-6, -280, 6, 4, lighten(nose, 0.35), xf=H)
    elif species == "elephant":
        _mouth(c, H, -44, -226, p)
        curl = 10 + (p.mouth * 6) + (8 if p.mood == "wow" else 0)
        trunk = [(0, -292), (2, -250), (14, -214), (40, -196 - curl * 0.3), (66, -206 - curl), (72, -232 - curl)]
        c.line(trunk, out, 58, H)
        c.line(trunk, body, 48, H)
        for i in (1, 2, 3):
            tx, ty = trunk[i]
            c.line([(tx - 16, ty + 2), (tx + 16, ty - 2)], darken(body, 0.14), 4, H)
    elif species == "duck":
        beak = nose
        drop = p.mouth * 22
        c.ellipse(0, -250 + drop, 40, 15 + p.mouth * 6, darken(beak, 0.18), darken(beak, 0.4), 4, H)
        if p.mouth > 0.2:
            c.ellipse(0, -254 + drop * 0.6, 26, 7 + p.mouth * 8, MOUTH_DARK, xf=H)
        c.ellipse(0, -266, 54, 22, beak, darken(beak, 0.4), 4, H)
        c.ellipse(-16, -272, 4, 3, darken(beak, 0.45), xf=H)
        c.ellipse(16, -272, 4, 3, darken(beak, 0.45), xf=H)
        for rot, dx in ((-24, -16), (0, 0), (24, 16)):
            F = Xf.rotate(rot + wig, dx, -440).then(H)
            c.ellipse(dx, -462, 12, 30, body, out, 4, F)

    # ---- head accessories
    if accessory == "bow":
        bx, by = -104, -424
        B = Xf.rotate(-18, bx, by).then(H)
        c.shape([(bx, by), (bx - 58, by - 34), (bx - 58, by + 34)], accent, acc_out, 4, B)
        c.shape([(bx, by), (bx + 58, by - 34), (bx + 58, by + 34)], accent, acc_out, 4, B)
        c.ellipse(bx, by, 17, 17, lighten(accent, 0.2), acc_out, 4, B)


def bounding_height(spec: dict) -> float:
    return {"bunny": 630, "cat": 500, "elephant": 470, "bear": 470, "duck": 500}[spec["species"]]
