#!/usr/bin/env python3
"""Stamp and signature candidate detection for scanned pages (vision stage baseline).

A heuristic baseline, not a trained model. It finds regions of *coloured ink*
(saturated red/blue/violet/green) and classifies each connected region:

  stamp      compact: the ink fills a good part of its bounding box, or the box is large and round-ish
  signature  sparse, stroke-like: little ink spread over a wide, short box

Black-ink signatures are NOT detected (indistinguishable from text by colour);
the report says so in "limitations". Measure it on your own document classes
before relying on it, and replace it with a model when the baseline isn't enough.

Outputs, all written to --out-dir:
  artifacts.json  schemaVersion, image size, artifacts[{kind, bbox_norm [x,y,w,h], ink_pixels, fill_ratio, confidence}]
  mask.png        8-bit L image, 255 where an artifact was found (full resolution)
  cleaned.png     the page with artifact pixels replaced by white, for better OCR of the text underneath

Exit codes: 0 ok, 2 usage, 3 unreadable/invalid input, 4 internal error.
Contract with the Java VisionRunner: paths only on the command line, never document content.
"""
import argparse
import json
import os
import sys
from collections import deque

EXIT_OK, EXIT_USAGE, EXIT_INPUT, EXIT_INTERNAL = 0, 2, 3, 4
SCHEMA_VERSION = 1
MAX_SIDE = 800  # analysis resolution; masks are scaled back to full size
# Untrusted input: only the decoders a scanned page needs. EPS (Ghostscript), PSD, GIF, TGA,
# PCF/BDF fonts and friends are where image-library CVEs cluster; they are never opened.
ALLOWED_FORMATS = ("PNG", "JPEG", "TIFF")
# A 600 dpi A3 page is ~ 7016 x 9921 = 70 Mpx. Anything far beyond that is a decompression bomb.
MAX_PIXELS = 120_000_000


def coloured_ink(rgb, min_saturation=90):
    """Boolean mask of saturated, not-too-light pixels. rgb: HxWx3 uint8 array."""
    import numpy as np
    from PIL import Image
    hsv = np.asarray(Image.fromarray(rgb).convert("HSV"), dtype=np.int16)
    s, v = hsv[..., 1], hsv[..., 2]
    return (s >= min_saturation) & (v >= 40) & (v <= 245)


def components(mask, min_pixels):
    """4-connected components of a boolean mask -> list of (ys, xs) index arrays. Pure Python BFS."""
    import numpy as np
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        q = deque([(y0, x0)])
        seen[y0, x0] = True
        ys, xs = [], []
        while q:
            y, x = q.popleft()
            ys.append(y)
            xs.append(x)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if len(ys) >= min_pixels:
            out.append((np.array(ys), np.array(xs)))
    return out


def dilate(mask, r):
    """Square dilation by r pixels using shifted ORs (no scipy)."""
    import numpy as np
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy == 0 and dx == 0:
                continue
            shifted = np.zeros_like(mask)
            ys = slice(max(dy, 0), mask.shape[0] + min(dy, 0))
            yd = slice(max(-dy, 0), mask.shape[0] + min(-dy, 0))
            xs = slice(max(dx, 0), mask.shape[1] + min(dx, 0))
            xd = slice(max(-dx, 0), mask.shape[1] + min(-dx, 0))
            shifted[ys, xs] = mask[yd, xd]
            out |= shifted
    return out


def merge_overlapping(boxes):
    """Union boxes (y0, y1, x0, x1) that intersect or nest, until stable.

    A round stamp is several separate ink regions (outer ring, inner ring, text)
    whose boxes nest; they are one artifact.
    """
    boxes = list(boxes)
    changed = True
    while changed:
        changed = False
        out = []
        while boxes:
            a = boxes.pop()
            i = 0
            while i < len(boxes):
                b = boxes[i]
                if a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]:
                    a = (min(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), max(a[3], b[3]))
                    boxes.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(a)
        boxes = out
    return sorted(boxes)


def analyse(img, min_area):
    import numpy as np
    from PIL import Image
    full_w, full_h = img.size
    scale = min(1.0, MAX_SIDE / max(full_w, full_h))
    small = img.convert("RGB").resize((max(1, round(full_w * scale)), max(1, round(full_h * scale))), Image.BILINEAR)
    rgb = np.asarray(small, dtype=np.uint8)
    ink = coloured_ink(rgb)
    # Anti-aliased edges of thin strokes are less saturated. Inside a box already identified as an
    # artifact, a looser threshold catches them so the cleaned page has no coloured residue.
    faint = coloured_ink(rgb, min_saturation=35)
    h, w = ink.shape
    # Join nearby strokes of one signature/stamp before labelling.
    grouped = dilate(ink, max(1, round(min(h, w) * 0.006)))
    min_pixels = max(4, int(min_area * h * w))

    boxes = [(ys.min(), ys.max() + 1, xs.min(), xs.max() + 1) for ys, xs in components(grouped, min_pixels)]
    artifacts = []
    region_mask = np.zeros_like(ink)
    for y0, y1, x0, x1 in merge_overlapping(boxes):
        box_ink = ink[y0:y1, x0:x1]
        ink_px = int(box_ink.sum())
        if ink_px < min_pixels:
            continue
        bw, bh = x1 - x0, y1 - y0
        fill = ink_px / float(bw * bh)
        aspect = bw / float(bh)
        if fill >= 0.18 or (0.6 <= aspect <= 1.6 and bw * bh >= 0.004 * w * h):
            kind, conf = "stamp", min(0.95, 0.5 + fill)
        elif aspect >= 1.8 and fill < 0.18:
            kind, conf = "signature", min(0.9, 0.5 + (aspect - 1.8) * 0.1)
        else:
            kind, conf = "unknown_mark", 0.3
        region_mask[y0:y1, x0:x1] |= faint[y0:y1, x0:x1]
        artifacts.append({
            "kind": kind,
            "bbox_norm": [round(x0 / w, 4), round(y0 / h, 4), round(bw / w, 4), round(bh / h, 4)],
            "ink_pixels": ink_px,
            "fill_ratio": round(fill, 4),
            "confidence": round(conf, 2),
        })
    artifacts.sort(key=lambda a: (a["bbox_norm"][1], a["bbox_norm"][0]))
    mask_small = Image.fromarray((dilate(region_mask, 1) * 255).astype(np.uint8), "L")
    mask_full = mask_small.resize((full_w, full_h), Image.NEAREST)
    return artifacts, mask_full


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="page image (PNG/JPEG/TIFF)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--min-area", type=float, default=0.0005, help="smallest artifact as a fraction of the page area")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code else EXIT_OK
    if not (0 < args.min_area < 0.5):
        print("--min-area must be in (0, 0.5)", file=sys.stderr)
        return EXIT_USAGE
    try:
        from PIL import Image, UnidentifiedImageError
        import numpy  # noqa: F401
    except ImportError as e:
        print(f"missing dependency: {e.name}", file=sys.stderr)
        return EXIT_INTERNAL
    import warnings
    # Pillow raises above 2x MAX_IMAGE_PIXELS but only *warns* between 1x and 2x; make the limit exact.
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(args.input, formats=ALLOWED_FORMATS) as im:
                im.load()
                img = im.copy()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        print("image exceeds the pixel limit", file=sys.stderr)
        return EXIT_INPUT
    except (FileNotFoundError, UnidentifiedImageError, OSError) as e:
        print(f"cannot read image (allowed: {', '.join(ALLOWED_FORMATS)}): {type(e).__name__}", file=sys.stderr)
        return EXIT_INPUT
    if img.width < 8 or img.height < 8:
        print("image too small", file=sys.stderr)
        return EXIT_INPUT
    try:
        artifacts, mask = analyse(img, args.min_area)
        os.makedirs(args.out_dir, exist_ok=True)
        mask.save(os.path.join(args.out_dir, "mask.png"))
        cleaned = img.convert("RGB")
        cleaned.paste((255, 255, 255), mask=mask)
        cleaned.save(os.path.join(args.out_dir, "cleaned.png"))
        report = {
            "schemaVersion": SCHEMA_VERSION,
            "image": {"width": img.width, "height": img.height},
            "artifacts": artifacts,
            "limitations": ["black-ink signatures are not detected", "heuristic baseline; thresholds untuned for real scans"],
        }
        tmp = os.path.join(args.out_dir, ".artifacts.json.part")
        with open(tmp, "w") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp, os.path.join(args.out_dir, "artifacts.json"))
    except Exception as e:  # noqa: BLE001 - the Java side needs a clean exit code, not a traceback
        print(f"internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_INTERNAL
    print(json.dumps({"artifacts": len(artifacts)}))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
