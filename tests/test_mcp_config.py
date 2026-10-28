"""Guards for the project MCP config (.mcp.json + .claude/settings.json).

Claude Code fails to parse .mcp.json when a ${VAR} without a default is unset, which would also drop the headroom
server, so every env reference needs a `:-` default. Keys must come from the environment, never a literal.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = json.loads((ROOT / ".mcp.json").read_text())
SETTINGS = json.loads((ROOT / ".claude/settings.json").read_text())


def test_every_env_reference_has_a_default():
    for ref in re.findall(r"\$\{([^}]*)\}", (ROOT / ".mcp.json").read_text()):
        assert ":-" in ref, f"${{{ref}}} has no default"


def test_21st_server_reads_key_from_env():
    server = MCP["mcpServers"]["21st"]
    assert server["type"] == "http"
    assert server["url"] == "https://21st.dev/api/mcp"
    assert server["headers"]["x-api-key"] == "${API_KEY_21ST:-}"


def test_project_servers_are_enabled():
    assert set(SETTINGS["enabledMcpjsonServers"]) == set(MCP["mcpServers"])


def test_memory_server_runs_the_repo_package():
    server = MCP["mcpServers"]["memory"]
    assert server["args"] == ["-m", "memory_agent", "serve"]
    assert server["env"]["PYTHONPATH"] == "${CLAUDE_PROJECT_DIR:-.}"
    hooks = json.dumps(SETTINGS["hooks"])
    assert "memory_agent context" in hooks and "memory_agent export" in hooks
