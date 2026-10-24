"""Tests for skill-anything-pro (.claude/skills/skill-anything-pro/scripts/).

Original request: the owner asked to install SkillAnything "with a more pro version". Upstream's run_eval.py never
detects a trigger (stream-json without --verbose; looks for a tool named after the skill), so the pro layer ships a
fixed trigger eval. A fake `claude` on PATH stands in for the CLI here; the live run is recorded in
.claude/skills-manager/STATUS.md.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PRO = Path(__file__).resolve().parent.parent / ".claude/skills/skill-anything-pro/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, PRO / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


te = load("trigger_eval")

INIT = {"type": "system", "subtype": "init", "skills": ["jq-helper"]}


def skill_use(name, tool="Skill"):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": tool, "input": {"skill": name}}]}}


def stream(*events):
    return "\n".join(json.dumps(e) for e in events)


def test_detects_skill_tool_call():
    assert te.skill_called(stream(INIT, skill_use("jq-helper")), "jq-helper") == (True, True)


def test_detects_namespaced_skill():
    assert te.skill_called(stream(INIT, skill_use("plugin:jq-helper")), "jq-helper") == (True, True)


def test_other_skill_or_tool_is_not_a_trigger():
    out = stream(INIT, skill_use("jq-helper-extra"), skill_use("jq-helper", tool="jq-helper"))
    assert te.skill_called(out, "jq-helper") == (True, False)


def test_no_init_event_is_reported():
    assert te.skill_called("Error: something\n", "jq-helper") == (False, False)


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """Install a fake `claude` that triggers when the query mentions jq; records its argv and cwd."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    script = bin_dir / "claude"
    script.write_text(f"""#!{sys.executable}
import json, os, sys
open({str(log)!r}, "a").write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\\n")
if os.environ.get("FAKE_CLAUDE_BROKEN"):
    print("Error: not logged in", file=sys.stderr); sys.exit(1)
skills = os.listdir(".claude/skills")
print(json.dumps({{"type": "system", "subtype": "init", "skills": skills}}))
if "jq" in sys.argv[2]:
    print(json.dumps({{"type": "assistant", "message": {{"content": [
        {{"type": "tool_use", "name": "Skill", "input": {{"skill": skills[0]}}}}]}}}}))
""")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    return log


QUERIES = [
    {"query": "jq filter help", "should_trigger": True},
    {"query": "capital of Indonesia", "should_trigger": False},
    {"query": "explain jq", "should_trigger": False},
]


def test_run_eval_summary_and_isolation(fake_claude):
    out = te.run_eval(QUERIES, "jq-helper", "Help with jq: filters", max_workers=2)
    s = out["summary"]
    assert (s["total"], s["passed"], s["errors"]) == (3, 2, 0)
    assert (s["true_positives"], s["true_negatives"], s["false_positives"], s["false_negatives"]) == (1, 1, 1, 0)

    calls = [json.loads(l) for l in fake_claude.read_text().splitlines()]
    assert all("--verbose" in c["argv"] and "stream-json" in c["argv"] for c in calls)
    cwds = {c["cwd"] for c in calls}
    assert len(cwds) == 3, "each query gets its own project"
    assert not any(Path(c).exists() for c in cwds), "temp projects are removed"


def test_description_with_colon_is_quoted(fake_claude, tmp_path):
    out = te.run_eval(QUERIES[:1], "jq-helper", "Use when: the user asks about jq", max_workers=1)
    assert out["summary"]["passed"] == 1


def test_cli_failure_is_an_error_not_a_miss(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_BROKEN", "1")
    with pytest.raises(RuntimeError, match="not logged in"):
        te.run_eval(QUERIES, "jq-helper", "Help with jq")


def test_parse_frontmatter_folded_description(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: x\ndescription: >\n  Line one\n  line two.\n---\nbody\n")
    assert te.parse_frontmatter(tmp_path) == ("x", "Line one line two.")


def test_run_loop_pro_swaps_in_fixed_eval():
    rl = load("run_loop_pro")
    assert rl.run_loop.run_eval is rl.trigger_eval.run_eval
