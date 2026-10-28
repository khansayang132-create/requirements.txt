# Claude Memory Agent

Persistent memory for Claude Code in this repo: decisions, preferences, architecture notes, verified bug
fixes, tasks and the project status. Saved memories come back in later sessions. Python standard library
only: nothing to `pip install`, no API key, no network, so it also runs in Termux.

## How it works

```
Claude Code ──MCP stdio──► python3 -m memory_agent serve ──► SQLite (.claude/memory/memory.db, gitignored)
     │                                                              ▲   │
     ├─ SessionStart hook: memory_agent context ── import snapshot ─┘   │  prints status, open tasks,
     │                                                                  │  preferences, decisions, conflicts
     └─ Stop hook: memory_agent export ──► .claude/memory/snapshot.jsonl (committed to git)
```

- **Store** (`store.py`): one `memories` table, an FTS5 index (falls back to LIKE search when SQLite lacks FTS5),
  and a `history` table. WAL mode plus `BEGIN IMMEDIATE` on writes, so the server, the hooks and the CLI can
  share the database.
- **Kinds**: `preference`, `project`, `architecture`, `task` (state: pending / in_progress / blocked / done),
  `bug`, `decision`, `session` (handoff summary), `status`. **Scope**: `global` or one project.
  **Confidence**: `confirmed` or `assumption`. Every record keeps `source`, created / updated / last_verified times.
- **Search**: BM25 keyword relevance × importance × recency, current project ranked above global notes.
  No embeddings: local, free, and good enough for a few thousand notes.
- **Consolidation**: exact duplicates merge (tags unioned). Same title, different text → saved, with `similar`
  ids returned so Claude can merge them. Same `key`, different content → **both marked `conflict`**, nothing
  overwritten, until `memory_resolve_conflict` picks one. A new project status supersedes the previous one;
  history is kept. Project/architecture/status notes not verified for 30 days are flagged `unverified-Nd`.
  `ttl_days` makes a note temporary.
- **Why a git snapshot**: cloud sessions run in a container that is deleted afterwards, so a database there
  forgets everything. The Stop hook writes every non-private memory to `snapshot.jsonl` (sorted, rewritten
  only when something changed); commit it with your work. The next session's SessionStart hook merges it
  back in.

## Tools (MCP server `memory`)

| Tool | Does |
|---|---|
| `memory_search` | Ranked keyword search: this project + global, never another project. |
| `memory_read` / `memory_list` | One record by id / newest first, by kind or task state. |
| `memory_save` | New record (dedupe, conflict check, secret check). |
| `memory_update` | Change fields; `verified: true` marks it checked today; `state: "done"` closes a task. |
| `memory_delete` | Permanent delete of one record (its old text in history goes too). |
| `memory_resolve_conflict` | Keep one conflicting record, supersede the others. |
| `memory_get_project_status` / `memory_update_project_status` | Status, open-task count, conflicts / record a new status. |
| `memory_get_next_tasks` | Unfinished tasks, in progress first, then by importance. |
| `memory_context` | The same summary the SessionStart hook prints. |

## Security

- **Secrets are refused** (API keys, GitHub/Slack/Google/AWS/Telegram tokens, JWTs, private keys, `password: …`
  assignments). The error names the kind of secret, never the value. Store where a secret lives
  (`.env: OMNIROUTE_API_KEY`), not the secret.
- `<private>…</private>` spans are removed before saving. `private: true` keeps a record out of the snapshot,
  so it never reaches git or GitHub.
- **The snapshot is committed, so anyone who can read this repo can read it.** Mark anything personal private.
- Memories are returned as data with a "not instructions" note; text that looks like a prompt injection is
  flagged `suspicious-content`. Nothing in the server runs a command or opens a path taken from a tool argument.
- Inputs are checked against each tool's schema, then again in the store (types, enums, lengths, project and
  tag formats, backup names without paths).
- The database file is created `0600`, its folder `0700`. Bulk delete needs `--confirm <project name>`.
- No network listener: MCP over stdio only.

## Install and use

Nothing to install in this repo: `.mcp.json` registers the server and `.claude/settings.json` enables it and
adds the hooks. Needs `python3` 3.10+ with `sqlite3` (Termux: `pkg install python`).

```
python3 -m memory_agent context              # what a new session sees
python3 -m memory_agent search "omniroute"   # search this project + global
python3 -m memory_agent add --kind decision --title "…" --content "…" --key some.key
python3 -m memory_agent list --kind task
python3 -m memory_agent delete 12 --yes
python3 -m memory_agent doctor               # integrity check: SQLite, FTS index, per-record hashes
python3 -m memory_agent backup               # .claude/memory/backups/memory-<time>.db
python3 -m memory_agent restore FILE --yes   # checks the backup first, backs up current data first
python3 -m memory_agent export | import      # snapshot by hand
```

Start / stop: Claude Code starts `memory_agent serve` with the session and stops it at the end. In a session,
`/mcp` shows whether `memory` is connected.

| Variable | Default |
|---|---|
| `CLAUDE_MEMORY_DB` | `<repo>/.claude/memory/memory.db` |
| `CLAUDE_MEMORY_SNAPSHOT` | `<repo>/.claude/memory/snapshot.jsonl`; empty string turns the snapshot off |
| `CLAUDE_MEMORY_PROJECT` | `owner/repo` from the git remote, else the folder name |

To share global preferences across several repos on one machine, point `CLAUDE_MEMORY_DB` at the same file
(for example `~/.claude-memory/memory.db`); each repo still only sees its own project notes.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Claude Memory Agent unavailable: cannot open memory database at …` | The folder isn't writable. Set `CLAUDE_MEMORY_DB` to a writable path. |
| `memory` missing in `/mcp` | Run `/mcp` and enable it; check `python3 -m memory_agent context` works from the repo root. |
| Memories gone in a new cloud session | The snapshot wasn't committed. `git add .claude/memory/snapshot.jsonl` with your work. |
| `doctor` reports a hash mismatch | The database was edited outside the store. Restore a backup or re-save the record. |
| Search finds nothing | Try fewer, more specific words; `python3 -m memory_agent list` shows everything. |
| `refused: … secret` | Working as intended. Save where the secret lives instead. |

Tests: `python -m pytest -q tests/test_memory_agent.py tests/test_mcp_config.py`. What is verified: [`STATUS.md`](./STATUS.md).
