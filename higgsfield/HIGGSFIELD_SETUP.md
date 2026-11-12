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

## The other "higgsfield": the open-source training framework (github.com/higgsfield-ai/higgsfield)

A different product from the image/video service: a GPU orchestration framework for training large language models
(ZeRO-3 / FSDP) across your own Ubuntu GPU servers, deployed through GitHub Actions.

| Check | Result |
|---|---|
| Installed | PASS: `pip install higgsfield==0.0.3` (latest on PyPI, Apache-2.0) into its own venv `.venv-higgsfield-train/` (gitignored). |
| Runs | PASS: `.venv-higgsfield-train/bin/higgsfield --help` lists `init`, `setup-nodes`, `build-experiments`, `run`, `ci`, `show-deploy-key`. |
| No clash | PASS: the global `higgsfield` is still the creative CLI 1.2.2. The two use the same command name, which is why this one lives in a venv. |
| Used for anything | NOT RUN: it needs SSH access to Ubuntu GPU nodes with passwordless sudo, and it installs Docker and deploy keys on them. None exist here, and the cartoon studio does not train models. |

Caution: it pins old crypto libraries (`cryptography` 41.0.7, `pyOpenSSL` 23.3.0, which have published security
advisories). Keep it isolated and don't use it on servers that matter until upstream updates those pins.
