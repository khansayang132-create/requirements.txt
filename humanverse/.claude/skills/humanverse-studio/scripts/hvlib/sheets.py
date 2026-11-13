"""Contact sheets for visual review (Pillow)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def sheet(paths: list[Path], out: Path, cols: int = 4, cell_w: int = 360, label: bool = True) -> Path:
    ims = [Image.open(p).convert("RGB") for p in paths]
    if not ims:
        raise ValueError("no images")
    r = cell_w / ims[0].width
    cw, ch = cell_w, int(ims[0].height * r)
    rows = (len(ims) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cw, rows * (ch + (22 if label else 0))), (245, 242, 236))
    d = ImageDraw.Draw(canvas)
    for i, (p, im) in enumerate(zip(paths, ims)):
        x, y = (i % cols) * cw, (i // cols) * (ch + (22 if label else 0))
        canvas.paste(im.resize((cw, ch)), (x, y))
        if label:
            d.text((x + 6, y + ch + 4), Path(p).stem, fill=(40, 40, 40))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out
