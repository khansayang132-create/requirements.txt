import os
from cartoon_studio.agents.team import AGENTS
from cartoon_studio.providers import RunwayAdapter, ProviderNotConfigured, SpendNotApproved

def test_ten_agents_import(): assert len(AGENTS)==10 and all(c() for c in AGENTS)
def test_missing_provider_key(monkeypatch):
 monkeypatch.delenv("RUNWAYML_API_SECRET",raising=False)
 try: RunwayAdapter()
 except ProviderNotConfigured: assert True
 else: assert False


def test_codex_agent_definitions_are_valid_toml():
    import tomllib
    from pathlib import Path

    files = sorted((Path(__file__).parents[1] / ".codex" / "agents").glob("*.toml"))
    assert len(files) == 5
    for path in files:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        assert data.get("name")
        assert data.get("description")
        assert data.get("developer_instructions")


def test_integration_docs_state_host_limitations():
    from pathlib import Path

    root = Path(__file__).parents[1]
    voice = (root / "documentation/integrations/voice-notify.md").read_text(encoding="utf-8")
    empire = (root / "documentation/integrations/empire-llm-codex.md").read_text(encoding="utf-8")
    assert "BLOCKED" in voice
    assert "NOT TESTED" in empire
    assert "No credits or money were spent" in empire


def test_integration_audit_is_non_mutating_and_has_explicit_statuses(tmp_path):
    from cartoon_studio.integrations import integration_report
    (tmp_path / "AGENTS.md").write_text("guardrails", encoding="utf-8")
    (tmp_path / ".codex/agents").mkdir(parents=True)
    (tmp_path / "documentation/integrations").mkdir(parents=True)
    (tmp_path / "documentation/integrations/empire-llm-codex.md").write_text("guide", encoding="utf-8")
    report = integration_report(tmp_path)
    assert report["schema_version"] == 1
    assert report["safety"] == {"credentials_read": False, "external_model_calls": 0, "paid_calls": 0, "settings_mutated": False}
    rows = {row["name"]: row for row in report["integrations"]}
    assert rows["Codex Dev Workflows project contract"]["status"] == "PASS"
    assert rows["Empire LLM for Codex"]["status"] == "NOT_TESTED"
