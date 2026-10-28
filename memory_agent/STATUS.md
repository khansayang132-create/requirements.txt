# Claude Memory Agent: status

Last checked 2026-10-28 in a Claude Code cloud session (Linux, Python 3.13.17, SQLite 3.45.1 with FTS5,
Claude Code 2.1.312). PASS = verified with the evidence named. Update this file when what is verified changes.

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Existing environment inspected | PASS | Python repo (bot, APEX, agency); `.mcp.json` already used for project MCP servers; no existing Claude memory (HarnessFlow `repo_info/` is for HarnessFlow runs only, `~/.claude/projects/*/memory` empty). |
| Integration method chosen from real capabilities | PASS | Claude Code is installed and reads `.mcp.json` + `.claude/settings.json`: project MCP server (stdio) + SessionStart/Stop hooks + CLAUDE.md instructions. |
| Persistent storage | PASS | `test_record_survives_reopen`, `test_unfinished_task_survives_restart` (two separate server processes). |
| Search | PASS | `test_search_finds_relevant_record_first`, `test_search_without_fts5_falls_back_to_like`. |
| Update and delete | PASS | `test_update_changes_fields_and_keeps_history`, `test_delete_removes_record_and_old_text`, `test_bulk_delete_requires_confirmation`. |
| Project-specific memory | PASS | `test_other_projects_memories_are_invisible` (search, get, delete). |
| Session continuity | PASS | `test_unfinished_task_survives_restart`; `test_snapshot_carries_memory_to_a_fresh_container`; `test_cli_hooks` (database deleted, context hook restores from the snapshot). |
| Duplicates / conflicts | PASS | `test_exact_duplicate_merges`, `test_conflicting_facts_are_flagged_not_merged`, `test_status_update_supersedes_previous_status`. |
| Security protections | PASS | `test_secrets_are_refused_without_echo` (6 secret types), `test_private_tags_injection_flags_and_names`, `test_mcp_argument_validation`. |
| Failure handling | PASS | `test_unavailable_storage_gives_clear_error`, `test_malformed_requests` (bad JSON, unknown method/tool, missing argument; server stays up), `test_doctor_detects_tampering_and_backup_restores`. |
| Automated tests created and run | PASS | `tests/test_memory_agent.py`: 28 passed; `tests/test_mcp_config.py`: 4 passed. |
| Claude integration tested | PASS (headless) | `claude -p` (Claude Code 2.1.312, Haiku 5.5) with this server: called `memory_save` then `memory_get_next_tasks` and answered "1 — Live check"; the record was in the database afterwards. Again with the committed `.mcp.json` entry: `memory_update_project_status` + `memory_get_project_status` returned project `khansayang132-create/requirements.txt`. The hooks ran in those sessions (they created `.claude/memory/`). |
| Interactive session shows the tools | NOT TESTED | `claude mcp list` in a nested CLI showed `memory` as "Pending approval", same as the existing `headroom` server, which does load in real sessions through `enabledMcpjsonServers`. Pending task #6 in the snapshot asks the next session to confirm. |
| Installation instructions | PASS | `memory_agent/README.md`. |
| Existing configuration preserved | PASS | `.mcp.json` and `.claude/settings.json` only gained entries; existing servers and hooks unchanged (diff reviewed); `tests/test_mcp_config.py` still passes. |
| Termux | NOT TESTED | Stdlib only, so it should work; not run on a phone. If that Python's SQLite lacks FTS5, search uses the LIKE fallback (tested). |

## Not implemented (on purpose)

- **Semantic (embedding) search.** It would need a model download or a paid API; keyword BM25 is enough for now.
- **Reading past conversations.** Claude Code gives hooks no general access to old transcripts, so memory holds
  only what Claude or the owner saves.
- **Automatic capture of every tool call** (the claude-mem approach). It stores a lot of noise and risks storing
  secrets from command output; memories here are saved deliberately.
