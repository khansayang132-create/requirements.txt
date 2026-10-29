"""HALLMARK checker (.claude/skills/hallmark/scripts/hallmark_check.py) and install layout."""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude/skills/hallmark"
SCRIPT = SKILL / "scripts/hallmark_check.py"

spec = importlib.util.spec_from_file_location("hallmark_check", SCRIPT)
hc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hc)

GOOD = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Jadwal</title>
<style>:root{--fg:#1a1a1a;--bg:#ffffff} body{margin:0;padding:16px;color:var(--fg);background:var(--bg);font:16px system-ui}
button{transition:background .2s} button:focus-visible{outline:3px solid #4b2bd6}
@media (prefers-reduced-motion: reduce){*{transition:none}}</style></head>
<body><main><h1>Jadwal</h1><h2>Minggu ini</h2>
<label for="d">Tanggal</label><input id="d" type="date">
<label>Catatan <textarea></textarea></label>
<button>Simpan jadwal</button><a href="/help"><img src="i.svg" alt="Bantuan"></a>
<input type="hidden" name="t"></main></body></html>"""


def rules(html):
    return {f["rule"] for f in hc.check_html(html)}


def test_clean_page_has_no_findings():
    assert hc.check_html(GOOD) == []


@pytest.mark.parametrize("old,new,rule", [
    ('lang="id"', "", "DOC-LANG"),
    ("<title>Jadwal</title>", "<title> </title>", "DOC-TITLE"),
    ("initial-scale=1", "initial-scale=1, user-scalable=no", "DOC-ZOOM"),
    ("initial-scale=1", "initial-scale=1, maximum-scale=1", "DOC-ZOOM"),
    ('<meta name="viewport" content="width=device-width, initial-scale=1">', "", "DOC-VIEWPORT"),
    ("<main>", "<div>", "LANDMARK-MAIN"),
    ('alt="Bantuan"', "", "IMG-ALT"),
    ("Simpan jadwal", "", "CTRL-NAME"),
    ('<img src="i.svg" alt="Bantuan">', "", "CTRL-NAME"),
    ('<label for="d">Tanggal</label>', "", "FORM-LABEL"),
    ("<label>Catatan <textarea></textarea></label>", '<textarea placeholder="Catatan"></textarea>', "FORM-LABEL"),
    ("<h2>", "<h3>", "HEADING-SKIP"),
    ("<h1>Jadwal</h1>", "", "HEADING-H1"),
    ('href="/help"', 'href="#"', "LINK-DEAD"),
    ("<button>Simpan jadwal</button>", '<div onclick="save()">Simpan</div>', "FAKE-BUTTON"),
    ("<button>Simpan", '<button tabindex="3">Simpan', "TABINDEX-POSITIVE"),
    ("<button>Simpan", '<button aria-hidden="true">Simpan', "ARIA-HIDDEN-FOCUS"),
    ('<input id="d"', '<input id="d"><span id="d"></span', "ID-DUP"),
    ("button:focus-visible{outline:3px solid #4b2bd6}", "button{outline:none}", "FOCUS-HIDDEN"),
    ("@media (prefers-reduced-motion: reduce){*{transition:none}}", "", "MOTION"),
    ("font:16px system-ui", "font-size:10px", "TEXT-TINY"),
    ("--fg:#1a1a1a", "--fg:#aaaaaa", "CONTRAST"),
])
def test_each_rule_fires_on_its_defect(old, new, rule):
    assert old in GOOD, old
    assert rule in rules(GOOD.replace(old, new, 1))


def test_aria_label_and_wrapping_label_count_as_names():
    page = GOOD.replace("<button>Simpan jadwal</button>", '<button aria-label="Tutup">×</button>')
    page = page.replace('<label for="d">Tanggal</label><input id="d" type="date">',
                        '<input type="date" aria-label="Tanggal">')
    assert hc.check_html(page) == []


def test_fake_button_with_role_and_tabindex_is_allowed():
    page = GOOD.replace("<button>Simpan jadwal</button>",
                        '<div role="button" tabindex="0" onclick="s()">Simpan</div>')
    assert "FAKE-BUTTON" not in rules(page)


def test_contrast_matches_wcag_reference_values():
    assert hc.contrast_ratio("#000", "#fff") == pytest.approx(21.0)
    assert hc.contrast_ratio("#fff", "#fff") == pytest.approx(1.0)
    assert round(hc.contrast_ratio("#767676", "#ffffff"), 2) == 4.54   # the classic AA-passing grey
    assert hc.contrast_ratio("#777777", "#ffffff") < 4.5
    with pytest.raises(ValueError):
        hc.contrast_ratio("blue", "#fff")


def test_contrast_resolves_tokens_and_grades_severity():
    found = hc.check_html(GOOD.replace("--fg:#1a1a1a", "--fg:#cccccc"))
    c = [f for f in found if f["rule"] == "CONTRAST"]
    assert c and c[0]["severity"] == "error"       # 1.61:1 is below even the 3:1 large-text bar
    found = hc.check_html(GOOD.replace("--fg:#1a1a1a", "--fg:#888888"))
    c = [f for f in found if f["rule"] == "CONTRAST"]
    assert c and c[0]["severity"] == "warn"        # 3.54:1: large text only


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], check=False, capture_output=True, text=True)


def test_cli_exit_codes(tmp_path):
    good, bad = tmp_path / "good.html", tmp_path / "bad.html"
    good.write_text(GOOD)
    bad.write_text(GOOD.replace('lang="id"', ""))
    assert run("check", str(good)).returncode == 0
    r = run("check", str(bad), "--json")
    assert r.returncode == 1 and json.loads(r.stdout)[str(bad)][0]["rule"] == "DOC-LANG"
    warn_only = tmp_path / "warn.html"
    warn_only.write_text(GOOD.replace("<main>", "<div>"))
    assert run("check", str(warn_only)).returncode == 0
    assert run("check", str(warn_only), "--strict").returncode == 1
    assert run("contrast", "#000", "#fff").returncode == 0
    assert run("contrast", "#999", "#fff").returncode == 1
    assert run("contrast", "nope", "#fff").returncode == 2
    assert run("check", str(tmp_path / "missing.html")).returncode == 2


def test_render_reports_blocked_not_pass_without_node(monkeypatch):
    monkeypatch.setattr(hc.shutil, "which", lambda name: None)
    assert hc.render("file:///x.html", Path("/tmp"))["status"] == "BLOCKED"


def _node_playwright():
    node = shutil.which("node")
    return bool(node) and subprocess.run([node, "-e", "require('playwright')"], check=False, capture_output=True).returncode == 0


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright not installed (CI); runs in cloud sessions")
def test_render_in_real_chromium(tmp_path):
    good = tmp_path / "good.html"
    good.write_text(GOOD.replace('<img src="i.svg" alt="Bantuan">', "Bantuan"))
    r = run("render", str(good), "--out", str(tmp_path / "shots"))
    result = json.loads(r.stdout)
    if result["status"] == "BLOCKED":
        pytest.skip(result.get("detail"))
    assert result["status"] == "PASS", result["problems"]
    assert r.returncode == 0
    assert all((tmp_path / "shots" / f).stat().st_size > 0 for f in ("phone-390.png", "tablet-768.png", "desktop-1440.png"))
    wide = tmp_path / "wide.html"
    wide.write_text(GOOD.replace("body{", "body{width:1200px;"))
    result = json.loads(run("render", str(wide), "--out", str(tmp_path / "w")).stdout)
    assert result["status"] == "FAIL" and any("sideways" in p for p in result["problems"])
    hidden = tmp_path / "hidden.html"
    hidden.write_text(GOOD.replace("button:focus-visible{outline:3px solid #4b2bd6}", "button{outline:none}"))
    result = json.loads(run("render", str(hidden), "--out", str(tmp_path / "h")).stdout)
    for vp in ("phone", "tablet", "desktop"):    # desktop puts a focusable link right beside the button
        assert f'{vp}: no visible focus indicator on button "Simpan jadwal"' in result["problems"]
    assert not any("input" in p for p in result["problems"])   # native date input rings are detected


def _frontmatter(path):
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(), re.DOTALL)
    assert m, f"{path} has no frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


def test_skill_and_agent_are_installed_and_valid():
    fm = _frontmatter(SKILL / "SKILL.md")
    assert fm["name"] == "hallmark" and 50 < len(fm["description"]) <= 1024
    agent = _frontmatter(ROOT / ".claude/agents/hallmark.md")
    assert agent["name"] == "hallmark" and "Bash" in agent["tools"]
    body = (SKILL / "SKILL.md").read_text()
    for link in re.findall(r"\]\(\./([^)]+)\)", body):        # every referenced file exists
        assert (SKILL / link).is_file(), link
