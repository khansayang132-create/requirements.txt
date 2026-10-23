"""Tests for the done-protocol skill's UI linter (.claude/skills/done-protocol/scripts/ui_lint.py).

Original request: the owner asked to upgrade the DONE Protocol UI spec into a production skill installed
for Claude Code. The linter is what makes the skill's hard rules checkable, so its hits and misses are pinned here.
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / ".claude/skills/done-protocol/scripts/ui_lint.py"
spec = importlib.util.spec_from_file_location("ui_lint", SCRIPT)
ui_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui_lint)


def rules(line):
    return {(h[3], h[2]) for h in ui_lint.lint_text(line)}


@pytest.mark.parametrize("line, rule", [
    ('<Dialog open={x}>', "MODAL"),
    ('import * as D from "@radix-ui/react-dialog";', "MODAL"),
    ('if (window.confirm("sure?")) go();', "MODAL"),
    ('alert("done")', "MODAL"),
    ('<div className="fixed inset-0 flex items-center justify-center bg-black/60">', "MODAL"),
    ('import { toast } from "sonner";', "TOAST"),
    ('<div className="rounded border">', "RADIUS"),
    ('<div className="rounded-md p-2">', "RADIUS"),
    ('<div className="hover:rounded-none">', "RADIUS"),
    ('<div className="rounded-t-sm">', "RADIUS"),
    ('<div className="bg-white text-black">', "LIGHT"),
    ('<div className="dark:bg-black">', "LIGHT"),
    ('<div className="bg-neutral-100">', "LIGHT"),
    ('<button className="bg-purple-600">', "ACCENT"),
    ('<div className="bg-[#111111]">', "HEX"),
])
def test_flags_errors(line, rule):
    assert (rule, "error") in rules(line)


@pytest.mark.parametrize("line", [
    '<div className="rounded-2xl border border-line bg-surface p-5">',
    '<button className="rounded-xl bg-violet-600 text-white hover:bg-violet-700">',
    '<span className="rounded-lg px-2.5 py-1 font-mono text-xs">',
    '<aside className="fixed inset-x-0 bottom-0 rounded-t-3xl md:w-[440px]">',
    '<span className="size-2 rounded-full bg-emerald-500">',
    '<div className="fixed inset-0 z-40 bg-black/60 md:hidden">',
    '<div className="bg-[#0d0d0f] border-[#26262a] hover:bg-[#141416]">',
    '<div className="bg-white/5">',
    'onConfirm(); obj.prompt(x); const roundedTotal = 1;',
    '<div className="rounded-md">  {/* ui-lint-ignore: third-party avatar */}',
])
def test_allows_compliant_code(line):
    assert not [r for r in rules(line) if r[1] == "error"], rules(line)


def test_float_and_width_are_warnings_only(tmp_path, capsys):
    (tmp_path / "a.tsx").write_text('const x = parseFloat(v);\n<aside className="fixed right-0 w-96">\n')
    assert ui_lint.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "WARN FLOAT" in out and "WARN WIDTH" in out


def test_cli_fails_on_error_and_skips_node_modules(tmp_path, capsys):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.tsx").write_text("<Modal/>\n")
    (tmp_path / "ok.tsx").write_text('<div className="rounded-2xl bg-surface"/>\n')
    assert ui_lint.main([str(tmp_path)]) == 0
    (tmp_path / "bad.tsx").write_text('<div className="rounded-sm"/>\n')
    assert ui_lint.main([str(tmp_path)]) == 1
    assert "bad.tsx:1: ERROR RADIUS" in capsys.readouterr().out


def test_skill_reference_code_passes_its_own_linter(tmp_path):
    """The copy-paste components must not teach code the linter rejects."""
    md = (SCRIPT.parent.parent / "reference/components.md").read_text()
    blocks = [b.split("\n", 1)[1] for b in md.split("```")[1::2] if b.startswith(("tsx", "ts", "css"))]
    errors = [h for b in blocks for h in ui_lint.lint_text(b) if h[2] == "error"]
    assert not errors, errors
