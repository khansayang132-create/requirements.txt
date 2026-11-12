# Higgsfield setup — what was actually installed and verified

Checked 2026-11-12 in the Claude Code cloud session. Status words: PASS = run and confirmed here; BLOCKED = needs the owner.

| Step | Result | Evidence |
|---|---|---|
| Environment | PASS | Linux x86_64, bash, Node 22.23.4, npm 10.9.9, git 2.43.0, Claude Code 2.1.322. No earlier Higgsfield install. |
| CLI installed | PASS | `npm install -g @higgsfield/cli` (official package, repository `github.com/higgsfield-ai/cli`, maintainers @higgsfield.ai). |
| CLI version | PASS | `higgsfield 1.2.2 (53301ea…) built 2026-10-16`. |
| CLI sign-in | **BLOCKED** | `higgsfield auth login` is a browser OAuth flow that returns to `localhost:<port>` **on the machine running the CLI**. In a cloud session that is the container, which your phone's browser cannot reach, so it waits forever. Run it on a computer you own (see below). No token was requested or stored. |
| Account (via the Higgsfield connector) | PASS | The official Higgsfield MCP connector in this Claude account is signed in: **plan free, 0.76 credits**. |
| Official skills | PASS | `claude plugin marketplace add higgsfield-ai/skills` + `claude plugin install higgsfield@higgsfield` → plugin `higgsfield` 0.14.0, scope user, enabled. |
| Claude Code discovers them | PASS | A fresh `claude -p` session listed all 9: higgsfield-generate, -soul-id, -product-photoshoot, -brandkit, -marketplace-cards, -websites, -faceless-video, -video-explainer, -youtube-thumbnail. |
| Test image | **BLOCKED (waiting for your OK)** | `z_image` 9:16 costs **0.15 credits** (cost preflight, nothing charged). Not generated without your approval. |

## Signing in the CLI yourself (on a computer, not the cloud session)

```bash
npm install -g @higgsfield/cli
higgsfield auth login          # opens your browser; approve there
higgsfield account status      # shows email, plan, credits
```

Never paste a token into chat or into this repository. In Claude Code cloud sessions use the Higgsfield connector
(claude.ai → Settings → Connectors), which is already signed in.

## Note on the skills

Some skill files tell an agent to run `curl … install.sh | sh` when the CLI is missing. The CLI is already installed
from npm here, so that path is not needed; don't pipe a download into a shell without reading it first.
