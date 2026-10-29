#!/usr/bin/env python3
"""HALLMARK checker: mechanical accessibility and UI-quality checks for HTML deliverables.

Commands:
  check FILE... [--json] [--strict]   static checks (stdlib only, no network)
  contrast FG BG                      WCAG 2.2 contrast ratio of two hex colors
  render FILE|URL [--out DIR]         real Chromium render at 390/768/1440 px via Node Playwright:
                                      horizontal overflow, console/page errors, keyboard focus
                                      visibility, screenshots. BLOCKED (exit 3) when Node or
                                      Playwright is missing; never reported as PASS.

Exit codes: 0 pass, 1 errors found (or warnings with --strict), 2 usage error, 3 BLOCKED.

These checks catch a known subset of problems. Passing them does not make a page accessible:
screen-reader behaviour, meaning, reading order and real-user usability still need a person.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
UNLABELLED_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image"}


# ---------------------------------------------------------------- contrast

def _hex_rgb(value):
    v = value.strip().lstrip("#")
    if len(v) in (3, 4):
        v = "".join(c * 2 for c in v[:3])
    elif len(v) in (6, 8):
        v = v[:6]
    else:
        raise ValueError(f"not a hex color: {value}")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb):
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg, bg):
    a, b = sorted((_luminance(_hex_rgb(fg)), _luminance(_hex_rgb(bg))), reverse=True)
    return (a + 0.05) / (b + 0.05)


# ---------------------------------------------------------------- static HTML checks

class _Node:
    __slots__ = ("attrs", "line", "parent", "tag", "text")

    def __init__(self, tag, attrs, line, parent):
        self.tag, self.attrs, self.line, self.parent = tag, attrs, line, parent
        self.text = []


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.elements = []      # (node) in document order
        self.css = []           # contents of <style> and style="" attributes
        self.title_text = None
        self._in = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        node = _Node(tag, a, self.getpos()[0], self.stack[-1] if self.stack else None)
        self.elements.append(node)
        if "style" in a:
            self.css.append(a["style"])
        if tag == "img" and a.get("alt"):
            for anc in self.stack:  # an image's alt names its link/button
                anc.text.append(a["alt"])
        if tag not in VOID:
            self.stack.append(node)
        if tag in ("style", "title"):
            self._in = tag
            if tag == "title":
                self.title_text = ""

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in ("style", "title"):
            self._in = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._in == "style":
            self.css.append(data)
            return
        if self._in == "title":
            self.title_text += data
        for anc in self.stack:
            anc.text.append(data)


def _name(node):
    a = node.attrs
    return (a.get("aria-label", "").strip() or a.get("aria-labelledby", "").strip()
            or "".join(node.text).strip() or a.get("title", "").strip())


def _focusable(node):
    a = node.attrs
    if node.tag == "a" and "href" in a:
        return True
    if node.tag in ("button", "select", "textarea") or (node.tag == "input" and a.get("type") != "hidden"):
        return "disabled" not in a
    return "tabindex" in a and a["tabindex"].strip().lstrip("-").isdigit() and int(a["tabindex"]) >= 0


def _root_vars(css):
    out = {}
    for m in re.finditer(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\b", css):
        out.setdefault(m.group(1), m.group(2))  # first definition = default (usually light) theme
    return out


def _resolve(value, variables):
    value = value.strip()
    m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,\s*(#[0-9a-fA-F]{3,8}))?\s*\)", value)
    if m:
        return variables.get(m.group(1)) or m.group(2)
    m = re.match(r"#[0-9a-fA-F]{3,8}\b", value)
    return m.group(0) if m else None


def check_html(source):
    """Return a list of findings: {rule, severity, line, message}."""
    p = _Collector()
    p.feed(source)
    p.close()
    found = []

    def add(rule, sev, line, msg):
        found.append({"rule": rule, "severity": sev, "line": line, "message": msg})

    els = p.elements
    html = next((e for e in els if e.tag == "html"), None)
    if html is None or not html.attrs.get("lang", "").strip():
        add("DOC-LANG", "error", html.line if html else 1, "<html> needs a lang attribute (WCAG 3.1.1)")
    if not (p.title_text or "").strip():
        add("DOC-TITLE", "error", 1, "page needs a non-empty <title> (WCAG 2.4.2)")
    vp = next((e for e in els if e.tag == "meta" and e.attrs.get("name", "").lower() == "viewport"), None)
    if vp is None:
        add("DOC-VIEWPORT", "error", 1, 'missing <meta name="viewport" content="width=device-width, initial-scale=1">')
    else:
        content = vp.attrs.get("content", "").replace(" ", "").lower()
        mx = re.search(r"maximum-scale=([\d.]+)", content)
        if "user-scalable=no" in content or "user-scalable=0" in content or (mx and float(mx.group(1)) < 2):
            add("DOC-ZOOM", "error", vp.line, "viewport blocks zoom; remove user-scalable=no / maximum-scale (WCAG 1.4.4)")
    if not any(e.tag == "main" or e.attrs.get("role") == "main" for e in els):
        add("LANDMARK-MAIN", "warn", 1, "no <main> landmark")

    ids, labelled = {}, set()
    for e in els:
        if e.attrs.get("id"):
            ids.setdefault(e.attrs["id"], []).append(e.line)
        if e.tag == "label" and e.attrs.get("for"):
            labelled.add(e.attrs["for"])
    for i, lines in ids.items():
        if len(lines) > 1:
            add("ID-DUP", "error", lines[1], f'duplicate id="{i}" (lines {", ".join(map(str, lines))})')

    levels = []
    for e in els:
        a, tag = e.attrs, e.tag
        if tag == "img" and "alt" not in a:
            add("IMG-ALT", "error", e.line, '<img> has no alt (use alt="" only if decorative)')
        if tag == "button" and not _name(e):
            add("CTRL-NAME", "error", e.line, "<button> has no accessible name")
        if tag == "a" and "href" in a and not _name(e):
            add("CTRL-NAME", "error", e.line, "link has no accessible name")
        if tag == "a" and a.get("href", "").strip().lower() in ("#", "javascript:void(0)", "javascript:;", "javascript:"):
            add("LINK-DEAD", "warn", e.line, f'link href="{a["href"]}" goes nowhere; use a <button> or a real URL')
        if tag in ("div", "span", "li", "td", "img") and "onclick" in a and (not a.get("role") or "tabindex" not in a):
            add("FAKE-BUTTON", "error", e.line, f"<{tag} onclick> is not keyboard reachable; use <button>")
        if (tag in ("input", "select", "textarea") and a.get("type", "").lower() not in UNLABELLED_INPUT_TYPES):
            wrapped, anc = False, e.parent
            while anc is not None:
                if anc.tag == "label":
                    wrapped = True
                    break
                anc = anc.parent
            if not (wrapped or a.get("id") in labelled or a.get("aria-label", "").strip()
                    or a.get("aria-labelledby", "").strip()):
                hint = " (placeholder is not a label)" if a.get("placeholder") else ""
                add("FORM-LABEL", "error", e.line, f"<{tag}> has no label{hint} (WCAG 1.3.1, 3.3.2)")
        if a.get("aria-hidden", "").lower() == "true" and _focusable(e):
            add("ARIA-HIDDEN-FOCUS", "error", e.line, f'focusable <{tag}> is aria-hidden="true"')
        if a.get("tabindex", "").strip().isdigit() and int(a["tabindex"]) > 0:
            add("TABINDEX-POSITIVE", "warn", e.line, "positive tabindex breaks natural focus order")
        if re.fullmatch(r"h[1-6]", tag):
            lvl = int(tag[1])
            if levels and lvl > levels[-1] + 1:
                add("HEADING-SKIP", "warn", e.line, f"heading jumps from h{levels[-1]} to h{lvl}")
            levels.append(lvl)
    if not any(lvl == 1 for lvl in levels):
        add("HEADING-H1", "warn", 1, "no <h1>")

    css = "\n".join(p.css)
    if re.search(r"outline\s*:\s*(none|0)\b", css) and ":focus-visible" not in css:
        add("FOCUS-HIDDEN", "error", 1, "outline removed with no :focus-visible replacement (WCAG 2.4.7)")
    if re.search(r"@keyframes|animation\s*:|transition\s*:", css) and "prefers-reduced-motion" not in css:
        add("MOTION", "warn", 1, "animation/transition without a prefers-reduced-motion rule")
    for m in re.finditer(r"font-size\s*:\s*([\d.]+)px", css):
        if float(m.group(1)) < 12:
            add("TEXT-TINY", "warn", 1, f"font-size {m.group(1)}px is below 12px")

    variables = _root_vars(css)
    for block in re.finditer(r"([^{}]*)\{([^{}]*)\}", css):
        decls = {k.strip().lower(): v.strip() for k, _, v in
                 (d.partition(":") for d in block.group(2).split(";")) if v.strip()}
        fg = _resolve(decls.get("color", ""), variables)
        bg = _resolve(decls.get("background-color", "") or decls.get("background", ""), variables)
        if fg and bg:
            ratio = contrast_ratio(fg, bg)
            if ratio < 4.5:
                sel = block.group(1).strip().split("\n")[-1][:60] or "(inline)"
                add("CONTRAST", "error" if ratio < 3 else "warn", 1,
                    f"{sel}: {fg} on {bg} is {ratio:.2f}:1 (body text needs 4.5:1; large text 3:1)")
    return found


# ---------------------------------------------------------------- render (Chromium)

def render(target, out_dir):
    node = shutil.which("node")
    if not node:
        return {"status": "BLOCKED", "detail": "node not installed"}
    script = HERE / "render_check.cjs"
    try:
        r = subprocess.run([node, str(script), target, str(out_dir)], check=False, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"status": "BLOCKED", "detail": "render timed out after 180 s"}
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"status": "BLOCKED", "detail": (r.stderr or r.stdout).strip()[-400:] or "no output"}


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(prog="hallmark_check", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("files", nargs="+")
    c.add_argument("--json", action="store_true")
    c.add_argument("--strict", action="store_true", help="warnings also fail")
    k = sub.add_parser("contrast")
    k.add_argument("fg")
    k.add_argument("bg")
    r = sub.add_parser("render")
    r.add_argument("target")
    r.add_argument("--out", default="hallmark-render")
    args = ap.parse_args(argv)

    if args.cmd == "contrast":
        try:
            ratio = contrast_ratio(args.fg, args.bg)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        verdict = "AA body text" if ratio >= 4.5 else "AA large text / UI only" if ratio >= 3 else "FAILS AA"
        print(f"{ratio:.2f}:1  {verdict}")
        return 0 if ratio >= 4.5 else 1

    if args.cmd == "render":
        target = args.target
        if not re.match(r"https?://", target):
            path = Path(target).resolve()
            if not path.is_file():
                print(f"no such file: {target}", file=sys.stderr)
                return 2
            target = path.as_uri()
        result = render(target, Path(args.out).resolve())
        print(json.dumps(result, indent=2))
        return {"PASS": 0, "FAIL": 1}.get(result.get("status"), 3)

    report, failed = {}, False
    for f in args.files:
        try:
            findings = check_html(Path(f).read_text(encoding="utf-8"))
        except OSError as e:
            print(e, file=sys.stderr)
            return 2
        report[f] = findings
        if any(x["severity"] == "error" or args.strict for x in findings):
            failed = True
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for f, findings in report.items():
            errs = sum(x["severity"] == "error" for x in findings)
            print(f"{f}: {errs} error(s), {len(findings) - errs} warning(s)")
            for x in findings:
                print(f"  {x['severity'].upper():5} {x['rule']:18} line {x['line']}: {x['message']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
