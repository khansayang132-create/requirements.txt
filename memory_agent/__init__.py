"""Claude Memory Agent: persistent, project-scoped memory for Claude Code (stdlib only).

store.py      SQLite store: schema, save/update/delete, dedupe, conflicts, search, status, tasks, backup.
security.py   Input validation, secret rejection, <private> stripping, prompt-injection flags.
mcp_server.py MCP stdio server exposing the store as memory_* tools.
__main__.py   CLI: serve, context (SessionStart hook), export/import (Stop hook), search, backup, doctor.
"""
