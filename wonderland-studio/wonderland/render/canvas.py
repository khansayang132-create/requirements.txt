"""Drawing surface for the 2D cartoon renderer.

Everything is drawn as filled polygons on a canvas that is ``ss`` times larger than the
output and then box-downsampled, which gives clean antialiased edges from plain Pillow
(no Cairo/Skia needed, so it runs on GitHub runners, Linux boxes and Termux alike).

Coordinates passed to the drawing methods are in OUTPUT pixels (1080x1920 space).
``Xf`` is a 2D affine transform so a character part can be posed (rotated around a
pivot, squashed, mirrored) in its own local space.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Fredoka-Variable.ttf"

Color = tuple[int, int, int]


def hex_rgb(value: str | Color) -> Color:
    if isinstance(value, tuple):
        return value
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def mix(a: str | Color, b: str | Color, t: float) -> Color:
    a, b = hex_rgb(a), hex_rgb(b)
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), round(a[2] + (b[2] - a[2]) * t))


def darken(c: str | Color, t: float = 0.25) -> Color:
    return mix(c, (30, 25, 50), t)


def lighten(c: str | Color, t: float = 0.3) -> Color:
    return mix(c, (255, 255, 255), t)


class Xf:
    """Affine transform [a c e; b d f]. Compose with ``@``-like ``then``; apply to points."""

    __slots__ = ("a", "b", "c", "d", "e", "f")

    def __init__(self, a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f

    @staticmethod
    def translate(x: float, y: float) -> "Xf":
        return Xf(1, 0, 0, 1, x, y)

    @staticmethod
    def scale(sx: float, sy: float | None = None) -> "Xf":
        return Xf(sx, 0, 0, sx if sy is None else sy, 0, 0)

    @staticmethod
    def rotate(deg: float, px: float = 0.0, py: float = 0.0) -> "Xf":
        r = math.radians(deg)
        cs, sn = math.cos(r), math.sin(r)
        return Xf(cs, sn, -sn, cs, px - cs * px + sn * py, py - sn * px - cs * py)

    def then(self, outer: "Xf") -> "Xf":
        """Return the transform that applies ``self`` first, then ``outer``."""
        o, s = outer, self
        return Xf(
            o.a * s.a + o.c * s.b, o.b * s.a + o.d * s.b,
            o.a * s.c + o.c * s.d, o.b * s.c + o.d * s.d,
            o.a * s.e + o.c * s.f + o.e, o.b * s.e + o.d * s.f + o.f,
        )

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def pts(self, points) -> list[tuple[float, float]]:
        a, b, c, d, e, f = self.a, self.b, self.c, self.d, self.e, self.f
        return [(a * x + c * y + e, b * x + d * y + f) for x, y in points]

    @property
    def mag(self) -> float:
        """Average scale factor (for line widths)."""
        return math.sqrt(abs(self.a * self.d - self.b * self.c))


IDENTITY = Xf()


@lru_cache(maxsize=256)
def _unit_ellipse(n: int) -> tuple[tuple[float, float], ...]:
    return tuple((math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n)) for i in range(n))


def ellipse_points(cx: float, cy: float, rx: float, ry: float, n: int | None = None) -> list[tuple[float, float]]:
    if n is None:
        n = max(16, min(72, int((rx + ry) * 0.35)))
    return [(cx + rx * ux, cy + ry * uy) for ux, uy in _unit_ellipse(n)]


@lru_cache(maxsize=128)
def font(size: int, weight: int = 600, width: int = 100) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_PATH), size)
    try:
        f.set_variation_by_axes([weight, width])
    except OSError:  # pragma: no cover - static fallback
        pass
    return f


class Canvas:
    """Design space is always 1080x1920. ``ss`` is internal pixels per design pixel and
    ``k`` the integer box-downsample applied by ``finish``; output scale = ss / k.
    Full quality: ss=2, k=2 (1080x1920). Half-size preview: ss=1, k=2. Tests: ss=0.5, k=2."""

    def __init__(self, width: int, height: int, ss: float = 2, base: Image.Image | None = None, k: int = 2):
        self.w, self.h, self.ss, self.k = width, height, ss, k
        size = (round(width * ss), round(height * ss))
        self.img = base.copy() if base is not None else Image.new("RGB", size, (255, 255, 255))
        self.d = ImageDraw.Draw(self.img)

    @property
    def out_scale(self) -> float:
        return self.ss / self.k

    # ---- primitives (output-pixel coordinates) -------------------------------------
    def _s(self, pts):
        s = self.ss
        return [(x * s, y * s) for x, y in pts]

    def poly(self, pts, fill, outline=None, width: float = 0.0) -> None:
        sp = self._s(pts)
        if fill is not None:
            self.d.polygon(sp, fill=fill)
        if outline is not None and width > 0:
            w = max(1, round(width * self.ss))
            self.d.line(sp + [sp[0], sp[1]], fill=outline, width=w, joint="curve")

    def ellipse(self, cx, cy, rx, ry, fill, outline=None, width: float = 0.0, xf: Xf = IDENTITY, n: int | None = None) -> None:
        self.poly(xf.pts(ellipse_points(cx, cy, rx, ry, n)), fill, outline, width * xf.mag)

    def shape(self, pts, fill, outline=None, width: float = 0.0, xf: Xf = IDENTITY) -> None:
        self.poly(xf.pts(pts), fill, outline, width * xf.mag)

    def line(self, pts, fill, width: float, xf: Xf = IDENTITY, caps: bool = True) -> None:
        tp = xf.pts(pts)
        sp = self._s(tp)
        w = max(1, round(width * xf.mag * self.ss))
        self.d.line(sp, fill=fill, width=w, joint="curve")
        if caps:
            r = w / 2
            for x, y in (sp[0], sp[-1]):
                self.d.ellipse([x - r, y - r, x + r, y + r], fill=fill)

    def capsule(self, x0, y0, x1, y1, width, fill, outline=None, owidth: float = 0.0, xf: Xf = IDENTITY) -> None:
        if outline is not None and owidth > 0:
            self.line([(x0, y0), (x1, y1)], outline, width + 2 * owidth, xf)
        self.line([(x0, y0), (x1, y1)], fill, width, xf)

    def rrect(self, x0, y0, x1, y1, r, fill, outline=None, width: float = 0.0) -> None:
        s = self.ss
        self.d.rounded_rectangle([x0 * s, y0 * s, x1 * s, y1 * s], radius=r * s, fill=fill,
                                 outline=outline, width=max(1, round(width * s)) if outline else 0)

    def rect(self, x0, y0, x1, y1, fill) -> None:
        s = self.ss
        self.d.rectangle([x0 * s, y0 * s, x1 * s, y1 * s], fill=fill)

    def finish(self) -> Image.Image:
        return self.img.reduce(self.k) if self.k > 1 else self.img


def vertical_gradient(width: int, height: int, stops: list[tuple[float, str | Color]]) -> Image.Image:
    """Smooth vertical gradient through (position 0..1, colour) stops."""
    import numpy as np

    ys = np.linspace(0.0, 1.0, height)
    pos = [p for p, _ in stops]
    out = np.zeros((height, 3), dtype=np.float32)
    for ch in range(3):
        out[:, ch] = np.interp(ys, pos, [hex_rgb(c)[ch] for _, c in stops])
    arr = np.repeat(out[:, None, :], width, axis=1).astype("uint8")
    return Image.fromarray(arr, "RGB")


def draw_text(img: Image.Image, text: str, cx: float, cy: float, size: int, fill, stroke=None, stroke_width: int = 0,
              weight: int = 600, anchor: str = "mm") -> None:
    d = ImageDraw.Draw(img)
    d.text((cx, cy), text, font=font(size, weight), fill=fill, anchor=anchor,
           stroke_width=stroke_width, stroke_fill=stroke)


def text_width(text: str, size: int, weight: int = 600) -> float:
    return font(size, weight).getlength(text)


# ---- easing -------------------------------------------------------------------------
def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def ease_out(t: float) -> float:
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t: float) -> float:
    t = clamp(t)
    return 3 * t * t - 2 * t * t * t


def ease_out_back(t: float, overshoot: float = 1.5) -> float:
    t = clamp(t) - 1
    return t * t * ((overshoot + 1) * t + overshoot) + 1
