#!/usr/bin/env python3
"""Visual regression for generated DOCX files (TSK-5.2.7).

Separate from the DOCX structure tests on purpose: a structurally perfect DOCX
can still render with overflow, clipped text or blank pages.

  render   DOCX -> PDF (LibreOffice) -> one PNG per page (pdftoppm)
  baseline render, then store pages + a manifest of tool versions as the baseline
  compare  render, then compare page by page against a baseline; writes
           report.json and diff-<n>.png for every page that differs

Exit codes: 0 pass, 1 visual differences, 2 usage error, 3 renderer missing.
A missing renderer is reported explicitly, never treated as a pass.

Checks per page: size, fraction of changed pixels (threshold), blank pages,
ink touching the page edge (clipping). Page count is checked overall.

Rendering depends on the LibreOffice version and installed fonts. Baselines
record both; compare warns when they differ from the current machine. Create
and compare baselines on the same CI image.

Requires: Pillow, LibreOffice (soffice), poppler-utils (pdftoppm).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

EXIT_PASS, EXIT_DIFF, EXIT_USAGE, EXIT_NO_RENDERER = 0, 1, 2, 3


def tool_versions():
    out = {}
    for name, args in (("soffice", ["--version"]), ("pdftoppm", ["-v"])):
        exe = shutil.which(name)
        if not exe:
            out[name] = None
            continue
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=120)
        out[name] = (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else "unknown"
    try:
        import PIL
        out["pillow"] = PIL.__version__
    except ImportError:
        out["pillow"] = None
    return out


def missing_tools():
    missing = [t for t in ("soffice", "pdftoppm") if not shutil.which(t)]
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("pillow")
    return missing


def render(docx, out_dir, dpi):
    """Returns the list of page PNG paths, in order."""
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        profile = os.path.join(tmp, "profile")
        # Isolated profile: a user's LibreOffice settings must not change the rendering.
        subprocess.run(["soffice", f"-env:UserInstallation=file://{profile}", "--headless",
                        "--convert-to", "pdf", "--outdir", tmp, docx],
                       check=True, capture_output=True, timeout=300)
        pdf = os.path.join(tmp, os.path.splitext(os.path.basename(docx))[0] + ".pdf")
        if not os.path.exists(pdf):
            raise RuntimeError("LibreOffice produced no PDF for " + docx)
        for f in os.listdir(out_dir):
            if f.startswith("page-") and f.endswith(".png"):
                os.remove(os.path.join(out_dir, f))
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", pdf, os.path.join(out_dir, "page")],
                       check=True, capture_output=True, timeout=300)
    pages = sorted(f for f in os.listdir(out_dir) if f.startswith("page-") and f.endswith(".png"))
    # pdftoppm pads numbers by page count (page-1 vs page-01); normalise to page-<n>.png.
    result = []
    for i, f in enumerate(sorted(pages, key=lambda s: int(s[5:-4])), start=1):
        target = os.path.join(out_dir, f"page-{i}.png")
        os.replace(os.path.join(out_dir, f), target)
        result.append(target)
    return result


def ink_fraction(img, white_threshold=245):
    g = img.convert("L")
    hist = g.histogram()
    total = sum(hist)
    ink = sum(hist[:white_threshold])
    return ink / total if total else 0.0


def edge_ink(img, margin_px, white_threshold=245):
    """True when any non-white pixel lies within margin_px of the page edge."""
    g = img.convert("L")
    w, h = g.size
    if margin_px <= 0 or w <= 2 * margin_px or h <= 2 * margin_px:
        return False
    strips = [(0, 0, w, margin_px), (0, h - margin_px, w, h), (0, 0, margin_px, h), (w - margin_px, 0, w, h)]
    for box in strips:
        lo, _ = g.crop(box).getextrema()
        if lo < white_threshold:
            return True
    return False


def compare_page(actual_path, baseline_path, pixel_tolerance, diff_path):
    from PIL import Image, ImageChops
    a = Image.open(actual_path).convert("RGB")
    b = Image.open(baseline_path).convert("RGB")
    if a.size != b.size:
        return {"sizeMismatch": [list(a.size), list(b.size)], "changedFraction": 1.0}
    diff = ImageChops.difference(a, b).convert("L")
    mask = diff.point(lambda v: 255 if v > pixel_tolerance else 0)
    hist = mask.histogram()
    changed = hist[255] / (a.size[0] * a.size[1])
    if changed > 0:
        # Red where pixels changed, over a faded copy of the actual page.
        faded = Image.blend(a, Image.new("RGB", a.size, "white"), 0.7)
        faded.paste(Image.new("RGB", a.size, (220, 0, 0)), mask=mask)
        faded.save(diff_path)
    return {"changedFraction": round(changed, 6)}


def cmd_render(args):
    pages = render(args.docx, args.out, args.dpi)
    print(json.dumps({"pages": pages}, indent=2))
    return EXIT_PASS


def cmd_baseline(args):
    pages = render(args.docx, args.baseline, args.dpi)
    manifest = {"source": os.path.basename(args.docx), "dpi": args.dpi, "pages": len(pages), "tools": tool_versions()}
    with open(os.path.join(args.baseline, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"baseline: {len(pages)} page(s) in {args.baseline}")
    return EXIT_PASS


def cmd_compare(args):
    manifest_path = os.path.join(args.baseline, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"no baseline manifest at {manifest_path}", file=sys.stderr)
        return EXIT_USAGE
    with open(manifest_path) as f:
        manifest = json.load(f)
    pages = render(args.docx, os.path.join(args.out, "actual"), manifest["dpi"])
    report = compare_dirs([p for p in pages], args.baseline, args.out, args.threshold, args.pixel_tolerance,
                          args.edge_margin, manifest)
    return EXIT_PASS if report["passed"] else EXIT_DIFF


def compare_dirs(actual_pages, baseline_dir, out_dir, threshold, pixel_tolerance, edge_margin, manifest):
    """Pure comparison, separated from rendering so it can be unit-tested without LibreOffice."""
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    baseline_pages = sorted((f for f in os.listdir(baseline_dir) if f.startswith("page-") and f.endswith(".png")),
                            key=lambda s: int(s[5:-4]))
    problems, page_results, warnings = [], [], []
    current = tool_versions()
    for tool in ("soffice", "pdftoppm"):
        if manifest.get("tools", {}).get(tool) != current.get(tool):
            warnings.append(f"{tool} differs from baseline: {manifest.get('tools', {}).get(tool)} -> {current.get(tool)}")
    if len(actual_pages) != len(baseline_pages):
        problems.append(f"page count {len(actual_pages)}, baseline {len(baseline_pages)}")
    for i, actual in enumerate(actual_pages, start=1):
        img = Image.open(actual)
        entry = {"page": i, "inkFraction": round(ink_fraction(img), 6)}
        if entry["inkFraction"] < 0.0005:
            problems.append(f"page {i} is blank")
        if edge_ink(img, edge_margin):
            entry["edgeInk"] = True
            problems.append(f"page {i} has content within {edge_margin}px of the edge (possible clipping)")
        if i <= len(baseline_pages):
            diff_path = os.path.join(out_dir, f"diff-{i}.png")
            entry.update(compare_page(actual, os.path.join(baseline_dir, baseline_pages[i - 1]), pixel_tolerance, diff_path))
            if entry.get("sizeMismatch"):
                problems.append(f"page {i} size {entry['sizeMismatch'][0]}, baseline {entry['sizeMismatch'][1]}")
            elif entry["changedFraction"] > threshold:
                problems.append(f"page {i}: {entry['changedFraction']:.4%} of pixels changed (threshold {threshold:.4%}); see diff-{i}.png")
        page_results.append(entry)
    report = {"passed": not problems, "problems": problems, "warnings": warnings, "threshold": threshold,
              "pixelTolerance": pixel_tolerance, "pages": page_results, "tools": current}
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(("PASS" if report["passed"] else "FAIL") + f": {len(page_results)} page(s); report {os.path.join(out_dir, 'report.json')}")
    for p in problems:
        print("  - " + p)
    for w in warnings:
        print("  ! " + w)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render"); r.add_argument("docx"); r.add_argument("--out", required=True); r.add_argument("--dpi", type=int, default=72)
    b = sub.add_parser("baseline"); b.add_argument("docx"); b.add_argument("--baseline", required=True); b.add_argument("--dpi", type=int, default=72)
    c = sub.add_parser("compare"); c.add_argument("docx"); c.add_argument("--baseline", required=True); c.add_argument("--out", required=True)
    c.add_argument("--threshold", type=float, default=0.002, help="max fraction of changed pixels per page (default 0.2%%)")
    c.add_argument("--pixel-tolerance", type=int, default=32, help="per-pixel grey difference ignored (antialiasing)")
    c.add_argument("--edge-margin", type=int, default=4, help="px from the page edge treated as clipping")
    args = ap.parse_args(argv)
    if not os.path.isfile(args.docx):
        print(f"not a file: {args.docx}", file=sys.stderr)
        return EXIT_USAGE
    missing = missing_tools()
    if missing:
        print("visual regression NOT RUN: missing " + ", ".join(missing), file=sys.stderr)
        return EXIT_NO_RENDERER
    return {"render": cmd_render, "baseline": cmd_baseline, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
