"""Docs stay true: every skill has valid frontmatter and all 16 sections, every documented
script exists and answers --help, and the .claude/skills links resolve."""

from __future__ import annotations

import re

import pytest
import yaml
from conftest import ROOT, run_script

SKILLS = ["youtube-auth", "youtube-upload", "youtube-analytics", "youtube-metadata", "youtube-thumbnail", "youtube-transcript", "youtube-pipeline"]
SECTIONS = ["Skill name", "Description", "Purpose", "When to use", "Required inputs", "Optional inputs", "Expected outputs", "Dependencies",
            "Exact execution commands", "CLI arguments", "Configuration", "Error handling", "Failure recovery", "Security considerations",
            "Integration with other skills", "Working examples"]
SCRIPTS = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "skills").glob("*/scripts/*.py"))


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_md_frontmatter_and_sections(skill):
    text = (ROOT / "skills" / skill / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "missing YAML frontmatter"
    front = yaml.safe_load(m.group(1))
    assert front["name"] == skill
    assert 40 < len(front["description"]) <= 1024
    for i, title in enumerate(SECTIONS, 1):
        assert re.search(rf"^## {i}\. {re.escape(title)}$", text, re.M), f"{skill}: section {i} '{title}' missing"


@pytest.mark.parametrize("skill", SKILLS)
def test_claude_skill_links_resolve(skill):
    link = ROOT / ".claude" / "skills" / skill
    assert link.is_symlink() and (link / "SKILL.md").is_file()


def test_documented_commands_point_to_real_scripts():
    docs = [ROOT / "README.md", ROOT / "CLAUDE.md", *(ROOT / "skills").glob("*/SKILL.md")]
    referenced = set()
    for doc in docs:
        referenced |= set(re.findall(r"skills/[\w-]+/scripts/\w+\.py", doc.read_text()))
    assert referenced, "no commands found in docs"
    missing = sorted(r for r in referenced if not (ROOT / r).is_file())
    assert not missing, missing
    assert set(SCRIPTS) <= referenced, f"undocumented scripts: {set(SCRIPTS) - referenced}"


@pytest.mark.parametrize("script", SCRIPTS)
def test_every_script_has_help(script):
    r = run_script(script, "--help")
    assert r.returncode == 0, r.stderr
    assert "usage:" in r.stdout
