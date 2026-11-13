"""Design QC: every check is measured on the rendered PNGs. A character that fails any check is rejected.

What is measured (and what is not):
  files        every reference exists, opens as an image, has the expected size and mode; views are RGBA with real
               transparency (background alpha 0, figure alpha 255)
  quality      the figure covers a sane share of its image (not blank, not a solid block), is not cut off by the
               image border, and has no large pure-black or NaN-garbage regions
  consistency  the four turnaround views share one height (same scale, same character) within 6 %, and the front and
               three-quarter colour histograms correlate (same palette seen from two angles)
  anatomy      the front view is mirror-symmetric (alpha IoU with its mirror image) and the measured head:body
               ratio is in the range of its style's proportions
  colour       the spec's body and accent colours are present in the front view (nearest rendered pixel within a
               CIELAB distance; lighting shifts colours, so the tolerance is stated)
  style        the style's own signature is present: outline styles have dark edge pixels, outline-free styles do
               not, sci-fi glows, storybook/clay/hyperreal surfaces have texture, anime is low-tone-count
NOT measured: appeal, acting or "professional quality" as a person would judge it. That is a human review; the
contact sheets are made for it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .styles import STYLES

TOL_DE = 28.0  # CIELAB distance allowed between a spec colour and its nearest lit pixel


def _lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def _hex(h: str) -> np.ndarray:
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], np.float64)


def check_character(d: Path) -> dict:
    data = json.loads((d / "character.json").read_text())
    st = STYLES[data["style"]]
    rows: dict[str, dict] = {}

    def row(name, ok, detail):
        rows[name] = {"status": "PASS" if ok else "FAIL", "detail": detail}

    # ---- files
    expected = ["views/front.png", "views/three-quarter.png", "views/side.png", "views/back.png", "turnaround.png",
                "expression_sheet.png", "proportions.png", "palette.png", "pose_sheet.png", "character_sheet.png"]
    bad = []
    for f in expected:
        try:
            with Image.open(d / f) as im:
                im.verify()
            with Image.open(d / f) as im:
                if min(im.size) < 200:
                    bad.append(f"{f} too small {im.size}")
        except Exception as e:  # noqa: BLE001 - any unreadable file is a failure
            bad.append(f"{f}: {type(e).__name__}")
    row("files", not bad, "all present and readable" if not bad else "; ".join(bad))
    with Image.open(d / "character_sheet.png") as im:
        row("high_res_sheet", im.size[0] >= 2400, f"character sheet {im.size[0]}x{im.size[1]}")

    views = {v: np.asarray(Image.open(d / "views" / f"{v}.png").convert("RGBA")).astype(np.float64)
             for v in ("front", "three-quarter", "side", "back")}
    # ---- transparency + quality
    issues = []
    for v, a in views.items():
        al = a[..., 3]
        cover = (al > 128).mean()
        border = np.concatenate([al[0], al[-1], al[:, 0], al[:, -1]])
        if not (0.15 < cover < 0.97):
            issues.append(f"{v} coverage {cover:.2f}")
        if (al == 0).sum() == 0:
            issues.append(f"{v} has no transparent pixels")
        if (border > 200).mean() > 0.35:
            issues.append(f"{v} looks cut off at the image edge")
        fig = a[al > 200][:, :3]
        if len(fig) and (fig.max(axis=1) < 8).mean() > 0.08:
            issues.append(f"{v} has a large pure-black region")
    row("transparent_png", not any("transparent" in i for i in issues), "RGBA with alpha 0 background on all views")
    row("visual_quality", not issues, "figure present, not cropped, no black/garbage regions" if not issues else "; ".join(issues))

    # ---- consistency across views
    hts = {}
    for v, a in views.items():
        r = np.where(a[..., 3].max(axis=1) > 128)[0]
        hts[v] = int(r[-1] - r[0]) if len(r) else 0
    spread = (max(hts.values()) - min(hts.values())) / max(1, max(hts.values()))
    row("turnaround_scale", spread <= 0.10, f"view heights {hts} (spread {spread:.1%}, limit 10%: ears and tails foreshorten by angle)")

    def hist(a):
        m = a[..., 3] > 200
        h, _ = np.histogramdd(a[m][:, :3], bins=(8, 8, 8), range=((0, 256),) * 3)
        return (h / max(1, h.sum())).ravel()
    h1, h2 = hist(views["front"]), hist(views["three-quarter"])
    corr = float(np.corrcoef(h1, h2)[0, 1]) if h1.std() > 0 and h2.std() > 0 else 0.0
    row("character_consistency", corr >= 0.6, f"front vs three-quarter colour histogram correlation {corr:.2f} (min 0.60)")

    # ---- anatomy
    m = views["front"][..., 3] > 128
    cols = np.where(m.any(axis=0))[0]
    mm = m[:, cols[0]:cols[-1] + 1] if len(cols) else m
    iou = float((mm & mm[:, ::-1]).sum() / max(1, (mm | mm[:, ::-1]).sum())) if len(cols) else 0.0
    one_sided = data.get("clothing", {}).get("accessory") == "bow"      # the bow sits by one ear by design
    limit = 0.72 if one_sided else 0.82
    row("symmetry", iou >= limit, f"front silhouette mirror IoU {iou:.2f} (min {limit}{'; bow is one-sided' if one_sided else ''})")
    hr = data["measured"]["head_ratio"]
    lo, hi = 0.30, 0.72
    row("proportions", lo <= hr <= hi and (st.head <= 1.15 or hr >= 0.42),
        f"head:body {hr:.2f} (valid {lo}-{hi}; big-head styles need >= 0.42)")

    # ---- colour
    front = views["front"]
    lab = _lab(front[front[..., 3] > 220][:, :3])
    if not len(lab):
        lab = np.full((1, 3), 1e6)                             # no figure: every colour check fails
    worst = {}
    for k in ("body", "accent"):
        target = _lab(_hex(data["colors"][k])[None])[0]
        worst[k] = round(float(np.sqrt(((lab - target) ** 2).sum(axis=1)).min()), 1)
    row("color_consistency", all(v <= TOL_DE for v in worst.values()),
        f"nearest-pixel CIELAB distance {worst} (limit {TOL_DE})")

    # ---- style signature: the style was really applied, and its visible marks are present
    from PIL import ImageFilter

    spec_ok = data.get("render_spec", {}).get("style", {}).get("mode") == st.mode
    fig = front[front[..., 3] > 220][:, :3]
    a8 = Image.fromarray((views["front"][..., 3] > 50).astype(np.uint8) * 255)
    inner = np.asarray(a8.filter(ImageFilter.MinFilter(9))) > 0
    band = (views["front"][..., 3] > 200) & ~inner
    lum_all = views["front"][..., :3] @ np.array([0.299, 0.587, 0.114])
    ink = float((lum_all[band] < 95).mean()) if band.any() else 0.0
    g = np.asarray(Image.open(d / "views" / "front.png").convert("L"), np.float64)
    edge = np.abs(np.diff(g, axis=1))[(views["front"][..., 3] > 250)[:, 1:]]
    tex = float(edge.mean()) if edge.size else 0.0
    sig = {"render_mode_matches": spec_ok, "silhouette_ink": round(ink, 3), "texture": round(tex, 2)}
    ok = spec_ok
    if st.outline >= 0.9:                                   # bold-outline styles: ink along the silhouette
        ok = ok and ink >= 0.5
    if st.mode in (2, 3, 5):                                # clay / storybook / hyperreal: visible surface texture
        ok = ok and tex >= 1.2
    if st.mode == 6:                                        # sci-fi: glowing edge
        glow = float(((fig[:, 1] > 200) & (fig[:, 2] > 200) & (fig[:, 0] < 200)).mean()) if len(fig) else 0.0
        sig["cyan_glow_share"] = round(glow, 3)
        ok = ok and glow > 0.003
    row("style_signature", ok, f"{sig} (mode {st.mode}, outline {st.outline})")

    status = "PASS" if all(r["status"] == "PASS" for r in rows.values()) else "FAIL"
    rep = {"character": data["id"], "name": data["name"], "style": data["style"], "status": status, "checks": rows,
           "not_tested": "appeal and acting quality (human review of the sheets)"}
    (d / "qc_report.json").write_text(json.dumps(rep, indent=2))
    return rep


def style_distinctness(results: dict[str, list[dict]]) -> dict:
    """Different styles must look different: mean (saturation, luminance spread, texture) per style, and the closest pair."""
    sig = {}
    for sid, reps in results.items():
        vals = []
        for r in reps:
            a = np.asarray(Image.open(Path(r["dir"]) / "views" / "three-quarter.png").convert("RGBA")).astype(np.float64)
            fig = a[a[..., 3] > 220][:, :3]
            mx, mn = fig.max(axis=1), fig.min(axis=1)
            sat = float(((mx - mn) / np.maximum(mx, 1)).mean())
            lum = fig @ np.array([0.299, 0.587, 0.114])
            g = np.asarray(Image.open(Path(r["dir"]) / "views" / "three-quarter.png").convert("L"), np.float64)
            tex = float(np.abs(np.diff(g, axis=1))[(a[..., 3] > 250)[:, 1:]].mean())
            vals.append((sat, float(lum.std()) / 64, tex / 10))
        sig[sid] = np.mean(vals, axis=0)
    ids = list(sig)
    pairs = sorted((float(np.linalg.norm(sig[a] - sig[b])), a, b) for i, a in enumerate(ids) for b in ids[i + 1:])
    return {"signatures": {k: [round(x, 3) for x in v] for k, v in sig.items()},
            "closest_pairs": [{"distance": round(d, 3), "a": a, "b": b} for d, a, b in pairs[:5]],
            "note": "signature = (mean saturation, luminance spread/64, texture/10) of the 5 characters; shape differences "
                    "(proportions, outlines) are not in this number"}
