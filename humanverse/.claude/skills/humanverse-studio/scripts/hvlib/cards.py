"""Title and credit cards (Pillow), subtitle timestamps."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]


def font(size: int, bold=True):
    for f in FONTS if bold else FONTS[1:]:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size)


def _gradient(size, top, bottom):
    w, h = size
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    for y in range(h):
        k = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)))
    return im


def _center(d, text, y, f, fill, w):
    bw = d.textbbox((0, 0), text, font=f)[2]
    d.text(((w - bw) / 2, y), text, font=f, fill=fill)


def title_card(out: Path, title: str, sub: str, size=(1920, 1080)) -> Path:
    w, h = size
    im = _gradient(size, (255, 214, 150), (232, 120, 96))
    d = ImageDraw.Draw(im)
    for i in range(14):                                      # soft kite shapes in the sky
        x, y, s = (i * 397) % w, (i * 211) % (h // 2), 18 + (i * 7) % 30
        d.polygon([(x, y - s), (x + s * 0.7, y), (x, y + s * 1.2), (x - s * 0.7, y)], fill=(255, 236, 200))
    _center(d, title, h * 0.38, font(int(h * 0.09)), (60, 34, 40), w)
    _center(d, sub, h * 0.52, font(int(h * 0.035), bold=False), (90, 50, 50), w)
    im.save(out)
    return out


def credits_card(out: Path, title: str, cast: list[str], size=(1920, 1080)) -> Path:
    w, h = size
    im = _gradient(size, (40, 44, 70), (90, 60, 90))
    d = ImageDraw.Draw(im)
    _center(d, title, h * 0.12, font(int(h * 0.06)), (255, 230, 190), w)
    _center(d, "Cast (original characters)", h * 0.27, font(int(h * 0.03)), (230, 220, 240), w)
    for i, c in enumerate(cast):
        _center(d, c, h * 0.34 + i * h * 0.055, font(int(h * 0.03), bold=False), (240, 240, 250), w)
    _center(d, "Modelled, rigged, animated, voiced, scored and edited by HUMANVERSE STUDIO", h * 0.7, font(int(h * 0.026), bold=False),
            (210, 205, 225), w)
    _center(d, "Blender (Cycles) · eSpeak NG · FFmpeg · all assets generated, none downloaded", h * 0.76, font(int(h * 0.022), bold=False),
            (190, 185, 210), w)
    im.save(out)
    return out


def ts(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
