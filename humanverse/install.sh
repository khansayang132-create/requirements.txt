#!/usr/bin/env bash
# Install HUMANVERSE STUDIO into another project: the skill, its 18 Claude Code subagents and an empty project tree.
#   ./install.sh /path/to/your/project
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DST="${1:?usage: install.sh /path/to/project}"
mkdir -p "$DST/.claude/skills" "$DST/.claude/agents" "$DST/project/cast" "$DST/project/story"
cp -R "$SRC/.claude/skills/humanverse-studio" "$DST/.claude/skills/"
cp "$SRC"/.claude/agents/hv-*.md "$DST/.claude/agents/"
[ -f "$DST/project/story/blocking.py" ] || cp "$SRC/.claude/skills/humanverse-studio/templates/blocking.example.py" "$DST/project/story/blocking.py"
find "$DST/.claude/skills/humanverse-studio" -name __pycache__ -prune -exec rm -rf {} +
echo "Installed into $DST"
echo "Next: cd $DST && python3.11 -m venv .venv && .venv/bin/pip install 'bpy==4.5.*' espeakng-loader Pillow pytest"
echo "      export HV_PROJECT=\$PWD/project; .venv/bin/python .claude/skills/humanverse-studio/scripts/hv.py doctor"
