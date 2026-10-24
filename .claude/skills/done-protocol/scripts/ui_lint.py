#!/usr/bin/env python3
"""Check DONE Protocol UI source against the skill's hard rules (SKILL.md section 1).

Usage: python3 ui_lint.py <dir-or-file> [...]
Prints `path:line: LEVEL RULE message` per hit. Exits 1 if any error, 0 otherwise (warnings don't fail).
Silence one line with `ui-lint-ignore` plus a reason in a comment on that line.
Line-based on purpose: no Node toolchain needed, runs anywhere Python 3.8+ does.
"""
import re
import sys
from pathlib import Path

EXTS = {".tsx", ".jsx", ".ts", ".js", ".css", ".html", ".mdx"}
SKIP_DIRS = {"node_modules", ".next", "dist", "build", "out", ".git", "coverage", ".turbo"}
PALETTE = {"000", "000000", "0d0d0f", "141416", "202024", "26262a"}

# (rule, level, regex, message). A class token is matched with (?<![\w-]) ... (?![\w-]) so `rounded-md` won't hit `rounded-md2`.
RULES = [
    ("MODAL", "error", re.compile(r"<(?:Modal|Dialog|AlertDialog)\b|from ['\"]@radix-ui/react-(?:alert-)?dialog['\"]"),
     "modal/dialog component; use InspectorPanel or TopDrawer"),
    ("MODAL", "error", re.compile(r"(?<![\w.])(?:window\.)?(?:alert|confirm|prompt)\("),
     "browser dialog; use an inline two-step button or TopDrawer"),
    ("MODAL", "error", re.compile(r"fixed inset-0\b(?=[^\"'`]*\bitems-center\b)(?=[^\"'`]*\bjustify-center\b)"),
     "centered overlay (a modal by another name); use InspectorPanel"),
    ("TOAST", "error", re.compile(r"from ['\"](?:sonner|react-hot-toast|react-toastify)['\"]|\btoast\("),
     "toast popup; use TopDrawer"),
    ("RADIUS", "error", re.compile(r"(?<![\w-])(?:[a-z]+:)*rounded(?:-[trblse]{1,2})?(?:-(?:none|sm|md))?(?![\w\[-])"),
     "sharp/small radius; use rounded-xl (controls), rounded-2xl (cards), rounded-3xl (drawers), rounded-lg (badges)"),
    ("LIGHT", "error", re.compile(r"(?<![\w-])dark:"), "dark: variant; the app is dark-only, style the base class"),
    ("LIGHT", "error", re.compile(r"(?<![\w-])(?:[a-z]+:)*bg-(?:white|(?:neutral|gray|zinc|slate|stone)-(?:50|100|200))(?![\w/-])"),
     "light surface; base is #000, surfaces #0d0d0f/#141416"),
    ("ACCENT", "error", re.compile(r"(?<![\w-])(?:[a-z]+:)*(?:bg|text|border|ring|from|to|via|fill|stroke|outline)-(?:purple|fuchsia)-\d"),
     "off-brand accent; use violet"),
    ("FLOAT", "warn", re.compile(r"\bparseFloat\(|\.toFixed\("),
     "float math; if this is money use parseUsdc/formatUsdc (bigint base units)"),
    ("WIDTH", "warn", re.compile(r"(?=.*\bright-0\b)(?=.*(?<![\w-])w-96(?![\w-]))"),
     "right sidebar is w-[440px]"),
]
HEX = re.compile(r"\[#([0-9a-fA-F]{3,8})\]")


def lint_text(text, path="<text>"):
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        if "ui-lint-ignore" in line:
            continue
        for rule, level, rx, msg in RULES:
            if rx.search(line):
                hits.append((path, n, level, rule, msg))
        for m in HEX.finditer(line):
            if m.group(1).lower() not in PALETTE:
                hits.append((path, n, "error", "HEX", f"#{m.group(1)} is off-palette; use a token (bg-surface, border-line, …)"))
    # one report per rule per line is enough
    return list(dict.fromkeys(hits))


def iter_files(paths):
    for p in map(Path, paths):
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix in EXTS and not SKIP_DIRS.intersection(f.relative_to(p).parts):
                    yield f


def main(argv):
    if not argv:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    hits = []
    for f in iter_files(argv):
        hits += lint_text(f.read_text(encoding="utf-8", errors="replace"), str(f))
    for path, n, level, rule, msg in hits:
        print(f"{path}:{n}: {level.upper()} {rule} {msg}")
    errors = sum(1 for h in hits if h[2] == "error")
    print(f"{errors} error(s), {len(hits) - errors} warning(s)", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
