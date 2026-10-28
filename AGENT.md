# AGENT.md: AI Context for LSKhan

> **You are working on LSKhan** — the tools behind the TikTok account *LSKhan 🌏💞 Cinta Beda Negara* (an Indonesian wife and her Pakistani husband). This file is the index. Find the row that matches your task, then open the file it names. Do not guess; the files are short and load-bearing.

---

## 0. The 60-Second Orientation

**What this is.** One repo, three things:

1. **The Telegram bot** (`bot.py`): writes TikTok hooks, scripts, captions and ideas. It calls an AI through **OmniRoute**, an OpenAI-compatible gateway running **on the owner's Android phone in Termux**.
2. **The 24/7 runners**: `termux/install.sh` (the owner's real setup: phone, runit) and `service/install.sh` (Linux with systemd).
3. **APEX** (`apex/`): a video production pipeline. Spec → script → narration → real Blender 3D renders → ffmpeg edit → technical QA → manifest.

**Who uses it.** The owner works from a phone. They have no Linux computer. Anything they must do by hand has to work as one paste into Termux, with Termux's real paths and folder names.

**What that means for you.**
- Viewer-facing text is **Bahasa Indonesia**, warm and natural. Code, comments and docs are English.
- Content follows the LSKhan rules: curiosity without lying, no fake drama, no invented serious events, the husband never looks stupid and the wife never cruel, respectful Islamic and family topics. These rules live in `CINTA_PERSONA` in `bot.py` and `RULES` in the LSKhan Studio app. Change them in both or neither.
- **Nothing is "done" without evidence.** A claim of success needs a test run, a CI run, or an output file you inspected. `apex/STATUS.md` is the model: IMPLEMENTED / VERIFIED / BLOCKED / NOT IMPLEMENTED.

**The one rule.** If a task touches an existing system, the file that owns it is the source of truth. This index only points. If a rule below conflicts with that file, the file wins.

---

## 1. Documentation Map

> An index, not a summary. Read the row, open the file.

### The bot
| Topic | Source of Truth |
|---|---|
| **Commands & personas** | [`bot.py`](./bot.py): `/caption` `/idea` (jastip persona), `/hook` `/script` (`CINTA_PERSONA`), `/ping` (connection check), `/start` `/help`. Long replies are split at 4000 chars. |
| **AI connection** | [`bot.py`](./bot.py) top block + [`.env.example`](./.env.example). OmniRoute first (`OMNIROUTE_API_KEY`, `OMNIROUTE_BASE_URL`, `OMNIROUTE_MODEL`), then direct OpenAI. On the owner's phone: base URL `http://127.0.0.1:20128/v1`, model `cc/claude-opus-5-5`. Optional `HEADROOM_BASE_URL` (Headroom proxy, `http://127.0.0.1:8765/v1`) is tried first; `chat()` falls back to the direct route on connection errors only. |
| **Headroom for Claude Code** | [`scripts/headroom.sh`](./scripts/headroom.sh) `setup` / `mcp` / `status`. Installs `headroom-ai[proxy]==0.41.0` into `~/.cache/lskhan-headroom` (~60 s, 780 MB), runs the proxy on 127.0.0.1:8765 with the beacon off, and `mcp` serves `headroom_compress` / `headroom_retrieve` / `headroom_stats` over stdio. |
| **21st.dev Magic for Claude Code** | [`.mcp.json`](./.mcp.json) server `21st` (remote HTTP, `https://21st.dev/api/mcp`, header `x-api-key: ${API_KEY_21ST:-}`), enabled in `.claude/settings.json`. Generates/fetches React UI components; useful only in a React project (this repo has none). Needs `API_KEY_21ST` in the session environment (cloud: environment secrets), never in a file. The `:-` default keeps `.mcp.json` parseable when the key is unset. Check with `/mcp`. The dev sandbox proxy denies `21st.dev` (403), so it is NOT VERIFIED live there. Guarded by `tests/test_mcp_config.py`. |
| **Setup for humans** | [`README.md`](./README.md): install, Termux 24/7, Linux 24/7, commands. |

### Running 24/7
| Topic | Source of Truth |
|---|---|
| **Android / Termux** (the real deployment) | [`termux/install.sh`](./termux/install.sh): termux-services (runit) services `lskhan-bot` and `lskhan-omniroute` (`check`: OmniRoute `/v1/models` with the `.env` key, model present; `update`: `git pull --ff-only`, pip, `npm install -g omniroute@latest`, restart, check), logs in `$PREFIX/var/log/sv/`, wake lock re-taken on every Termux open via `$PREFIX/etc/profile.d/lskhan-wakelock.sh`. Termux:Boot is **optional**. Many phones can't install it, and opening Termux once after a reboot is enough. Test: [`termux/test-termux.sh`](./termux/test-termux.sh). |
| **Owner's website** (served by the phone on port 8080) | Phone: `bash termux/install.sh site` runs ngrok as runit service `lskhan-site` at the owner's fixed ngrok domain, with basic auth (`SITE_AUTH`, required unless `SITE_PUBLIC=yes`); config in `~/.config/lskhan/ngrok.yml` (mode 600). Cloud sessions: [`scripts/site.sh`](./scripts/site.sh) `check` / `get PATH` / `url`, using the `SITE_URL` and `SITE_AUTH` environment secrets; the domain must be in the environment's Allowed domains. When the owner mentions "my website" or `localhost:8080`, run `scripts/site.sh check` first. `localhost` in this container is NOT the phone. |
| **Linux / systemd** | [`service/install.sh`](./service/install.sh): venv in `.venv/`, units `lskhan-bot` and optional `lskhan-omniroute`, run as the sudo user. Test: [`service/test-service.sh`](./service/test-service.sh). |

### APEX (video pipeline)
| Topic | Source of Truth |
|---|---|
| **Overview & usage** | [`apex/README.md`](./apex/README.md): stage diagram, CLI (`run`, `enqueue`, `worker`, `status`), module table. |
| **What is real vs blocked** | [`apex/STATUS.md`](./apex/STATUS.md): the completion-gate report. **Update it whenever you change what is verified.** |
| **Schemas & job states** | [`apex/apex/models.py`](./apex/apex/models.py): `ProductionSpec`, `Script`, `SceneSpec`, `Storyboard`, `SCENE_TEMPLATES`, `CAMERA_MOVES`, `ALLOWED_TRANSITIONS`. |
| **Scriptwriting** | [`apex/apex/script_engine.py`](./apex/apex/script_engine.py): providers, `review_script`, `write_script` (bounded revisions), `lock_script`. |
| **Voice** | [`apex/apex/tts.py`](./apex/apex/tts.py): `TTSProvider` interface, `ElevenLabsProvider` (when `ELEVENLABS_API_KEY` is set; voice Nilasari `NPDHDOOQCSyifTJZOe6J`), `EspeakProvider` fallback, `tts_from_env`, `normalize_for_speech` (Indonesian numbers and prices). |
| **3D scenes** | [`apex/apex/render3d.py`](./apex/apex/render3d.py): five templates, six camera moves, Cycles. Runs only in a Python that has `bpy`. |
| **Edit, captions, loudness** | [`apex/apex/assemble.py`](./apex/apex/assemble.py), [`apex/apex/subtitles.py`](./apex/apex/subtitles.py). |
| **QA** | [`apex/apex/qa.py`](./apex/apex/qa.py): technical checks plus sampled frames; creative review stays separate. |
| **Queue & worker** | [`apex/apex/jobs.py`](./apex/apex/jobs.py) (header explains leases, retries, dead letters), [`apex/apex/cli.py`](./apex/apex/cli.py). |
| **Autopilot & planner** | [`apex/apex/autopilot.py`](./apex/apex/autopilot.py): policy in `autopilot.json` next to the DB (emergency stop, daily cap, topic rules, approval gate); `run_plan` decides every plan entry. |
| **Ideas, review, backups** | [`ideas.py`](./apex/apex/ideas.py) (`apex.cli ideas` / `approve`; ideas always land unapproved), [`vision.py`](./apex/apex/vision.py) (`apex.cli review`; verdict computed locally from scores), [`backup.py`](./apex/apex/backup.py) (`apex.cli backup` / `verify-backup`). |
| **Control center** | [`apex/apex/dashboard.py`](./apex/apex/dashboard.py): read-only web page (`apex.cli dashboard`), binds 127.0.0.1. |
| **Publishing** | [`apex/apex/publishing.py`](./apex/apex/publishing.py): post state machine; dry-run adapter only. |
| **Acceptance sample** | [`apex/samples/money-mistake/`](./apex/samples/money-mistake/): spec, script, and the committed output with manifest and QA report. |

### Outside this repo
| Topic | Where |
|---|---|
| **LSKhan Studio** (phone app for hooks/scripts/captions/series) | Claude artifact `https://claude.ai/artifact/9Xfe4TpY8SdBy2epfKRi6p`. Uses the `sample` capability, so it runs on the viewer's own Claude plan. |
| **Private VPN + ad blocking** | Separate repo `khansayang132-create/lskhan-vpn`. Its own README, STATUS and tests. |

### Other tools
| Topic | Source of Truth |
|---|---|
| **HarnessFlow** (AI workflow pack, third-party) | [`.github/HarnessFlow/`](./.github/HarnessFlow/readme.md), vendored from `HangYu8123/HarnessFlow` @ `aa9f74c`. Opt-in: runs only on a filled-in template from `request_template/`. Generated files (`AGENTS.md`, `.github/copilot-instructions.md`, `.claude/agents/`, `.claude/rules/`, `.codex/agents/`) come from `bash .github/HarnessFlow/cli_setup.sh`; don't hand-edit them. CI (`check`) regenerates them and fails if anything changes: after editing `agents/*.agent.md`, run `python3 sync_agent_definitions.py` in the pack, then `bash .github/HarnessFlow/cli_setup.sh`, and commit. Repo memory lives in `.github/HarnessFlow/repo_info/` and is committed here. Its "don't commit" safety rule applies inside a HarnessFlow run only. |
| **DONE Protocol UI** (not LSKhan; Solana USDC escrow app) | [`.claude/skills/done-protocol/`](./.claude/skills/done-protocol/SKILL.md): `SKILL.md` (rules, pages, resolved spec conflicts), `reference/components.md` + `reference/protocol.md` (copy-paste code), `scripts/ui_lint.py` (enforces the hard rules; tested in `tests/test_done_ui_lint.py`). `.agents/skills/done_protocol` is a symlink to it. The app's code lives outside this repo. |
| **Skills manager** (find/install/verify Claude Code skills) | [`.claude/skills/skills-manager/`](./.claude/skills/skills-manager/SKILL.md): `SKILL.md` (commands incl. `disable`/`enable`, when to install, what needs the owner's OK), `scripts/skills_manager.py` (stdlib engine; tested in `tests/test_skills_manager.py`). State in `.claude/skills-manager/`: `config.json` (sources, policy), `registry.json` + `history.jsonl` (don't hand-edit), `reports/skills-audit.json`, [`STATUS.md`](./.claude/skills-manager/STATUS.md) (what's verified). Installed through it: `.claude/skills/frontend-design` (anthropics/skills). |
| **Engineering agency** (repo checks by specialist roles) | [`agency/README.md`](./agency/README.md) (commands, how it works), [`agency/STATUS.md`](./agency/STATUS.md) (what's verified). `python -m agency run health` runs deps, compile, both test suites, ruff, shellcheck, secret scan, pip-audit and bandit as roles with separate permissions; each result is verified by another role from the audit log. Code changes go through `run change` / `run patch` (commit to `agency/<branch>` in `agency/out/worktrees/`, tests on that branch, approvals required) and `run ship` (push, approval). `ask` = LLM planner (plan needs `approve-plan`). Allowlists in `agency/agency.json`. Nightly: `.github/workflows/agency-nightly.yml`. Tests: `tests/test_agency.py`, `tests/test_agency_full.py`. State in `agency/out/agency.db` (gitignored, so each session starts empty). In cloud sessions the SessionStart hook runs [`scripts/agency-setup.sh`](./scripts/agency-setup.sh), which builds `.venv` (~1 min first time, instant when requirements are unchanged); use `.venv/bin/python -m agency run health`. |
| **Spotify artist profiles** (not LSKhan) | [`.claude/skills/artist-profile/`](./.claude/skills/artist-profile/SKILL.md): `SKILL.md` (steps) + `template.md`. Profiles go in `profiles/<artist-slug>.md`; unknown fields stay `TBD`. |

---

## 2. Hard Constraints

Violating any of these is a bug, not a preference.

| Area | Rule |
|---|---|
| **Secrets** | Only in `.env` (gitignored). Never in code, tests, commits, PR text, logs or manifests. Never print a key. Rotate any key that appears in a chat. |
| **Bot AI calls** | `client.chat.completions.create` only. Gateways (OmniRoute) don't all support the Responses API, which is why it was removed. |
| **Bot reachability** | Every new bot command is registered in `main()` **and** listed in `/start` **and** in the README's Commands section. |
| **Bot access** | Every command that spends AI calls starts with `if not await allowed(update): return`, like `generate()` and `ping()`. The gate fails **closed**: with `TELEGRAM_ADMIN_ID` unset nobody passes, and the bot replies with the sender's ID to copy into `.env`. Never write `if ADMIN_ID and …`. |
| **Install scripts** | Must be idempotent (safe to re-run) and must have a matching CI test (`service` and `termux` jobs). Changing one without its test is a bug. |
| **Termux** | No systemd, no `sudo`, no `/etc`. Use `$PREFIX` and `$HOME`. Default to `127.0.0.1`, not `localhost`. |
| **APEX Python** | 3.13 (the `bpy` 5.x wheels need it). Blender code stays in `render3d.py` and runs as a subprocess; nothing else imports `bpy`. |
| **APEX honesty** | Never ship a fake output: no placeholder video, no invented metric, no post URL. A provider that isn't configured raises `ProviderUnavailable` / `TTSUnavailable`; it does not fall back to fake text. |
| **Publishing** | A post becomes `PUBLISHED` only from a provider response with `confirmed` and a `post_id`. Otherwise `PUBLICATION_STATUS_UNKNOWN`. |
| **QA** | Technical score and creative review are separate fields. Never fold "looks good" into the technical score. |
| **Autopilot** | New jobs from automation go through `run_plan` (approval, topics, daily cap). A worker never claims while the policy is paused. Don't add a path that enqueues around the policy. |
| **Dashboard** | Stays read-only and bound to 127.0.0.1 by default. Media is served only from a completed job's recorded `final` path, never from a URL path. |
| **Job states** | Change state only through `JobQueue` methods (they call `_move`, which enforces `ALLOWED_TRANSITIONS` and writes the audit log). Never `UPDATE jobs SET state=` directly. |
| **Facts in scripts** | No invented statistics, quotes or sources. Illustrative arithmetic is fine. `review_script` rejects unsourced percentages. |
| **Agency tools** | No general shell tool. New tools take fixed argv, a schema, a timeout and an approval flag, and return BLOCKED (not PASS) when their program or credential is missing. Anything that sends code off the machine, edits files, deploys or spends money sets `requires_approval=True`. Task states change only through `Store.move_task` / `move_mission`. |
| **Merging** | CI green on the branch head first: `check`, `service` ×2, `termux`, `apex`. |

---

## 3. Key File Locations

| Feature | Location |
|---|---|
| Bot | `bot.py` |
| Bot dependencies | `requirements.txt` (repo root) |
| Bot tests | `tests/test_bot.py`: admin gate, default gateway URL, reply splitting, route fallback |
| Env template (bot) | `.env.example` |
| Termux runner / test | `termux/install.sh`, `termux/test-termux.sh` |
| systemd runner / test | `service/install.sh`, `service/test-service.sh` |
| CI | `.github/workflows/test.yml` |
| APEX package | `apex/apex/` |
| APEX tests | `apex/tests/` (`test_core.py`, `test_jobs.py`, `test_media.py`) |
| APEX dependencies / image / env | `apex/requirements.txt`, `apex/Dockerfile`, `apex/.env.example` |
| APEX sample | `apex/samples/money-mistake/` |

**Constants worth knowing**
```
OmniRoute default port: 20128           (/v1 suffix required)
Headroom on the phone:  8765 → upstream via OPENAI_TARGET_API_URL=http://127.0.0.1:20128/v1
Telegram message cap:   4096 (bot splits at 4000)
APEX 9:16 render:       432×768, 24 fps, 8 Cycles samples
APEX loudness target:   -14 LUFS, true peak ≤ -0.5 dBFS
APEX scene pad / min:   0.45 s / 2.0 s
libass SRT canvas:      288 lines tall
```

---

## 4. Common Tasks

### Adding a bot command
1. Write the handler in `bot.py`. AI work goes through `generate(update, context, task, persona)`.
2. Register it in `main()`, add it to the `/start` text, add it to README → Commands.
3. `python -m py_compile bot.py` and `python -m pytest -q tests` (needs `pip install -r requirements.txt pytest`). CI runs both. Add a test in `tests/test_bot.py` for any new gate or routing rule.

### Changing the LSKhan content rules
Edit `CINTA_PERSONA` in `bot.py` **and** `RULES` in the LSKhan Studio artifact. Keep the meaning identical.

### Changing a 24/7 runner
1. Edit `termux/install.sh` or `service/install.sh`.
2. Update its test (`termux/test-termux.sh` or `service/test-service.sh`) to cover the change.
3. Push and wait for the `termux` / `service` jobs. Termux is tested in `termux/termux-docker`, which has no Android, so `am: app_process not found` in that log is expected.

### Working on APEX
```
cd apex
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                                   # 93 tests, ~16 s
.venv/bin/python -m apex.cli run --spec samples/money-mistake/spec.json \
    --script samples/money-mistake/script.json --project out/draft --fps 6 --samples 2   # ~6 min draft
```
- **Draft first.** Full quality (24 fps, 8 samples) is ~36 min for 30 s on 4 cores. Iterate at `--fps 6 --samples 2`.
- **Look at the frames.** Open `out/<project>/qa/frames/*.png` after every visual change. Technical QA can't see bad framing, giant subtitles or missing headlines; all three happened.
- **New scene template:** add it to `TEMPLATES` in `render3d.py` and `SCENE_TEMPLATES` in `models.py`, describe its params in `script_prompt`, and render it once at tiny size.
- **New TTS / LLM / publish provider:** implement the Protocol, raise `*Unavailable` without credentials, add a test with a fake or a local mock server (see `test_openai_compatible_provider_against_local_server`), then move the row in `STATUS.md`.
- **After a full run:** copy deliverables into `samples/<name>/output/` with local paths rewritten, and check that the video's SHA-256 matches the manifest.

---

## 5. Before You Code — Checklist

1. **Locate the system** in the map above. Open its file and read the header comment.
2. **Check `apex/STATUS.md`** before claiming a capability exists or works.
3. **Phone first.** If the owner must run something, it is one paste for Termux on Android with real paths (`~/lskhan-bot`, `$PREFIX`). Don't assume a computer, `sudo` or systemd.
4. **No secrets** in anything you write or print.
5. **Run the tests** that cover what you touched: `py_compile` for the bot, `pytest` for APEX, and CI for the runners.
6. **Report like STATUS.md:** what you ran, what passed, what's blocked and why, and the next action.

---

## 6. The Traps

Real failures from this repo, roughly in order of how much time they cost:

1. **`localhost` vs `127.0.0.1` on the phone.** The bot couldn't reach OmniRoute at `localhost:20128` until it used `127.0.0.1`. Use `127.0.0.1` in defaults and instructions.
2. **Assuming the owner has Linux.** The 24/7 setup was first built for systemd; the bot actually runs in Termux on Android. The phone's bot folder (`~/lskhan-bot`) was copied by hand, not cloned, so `git pull` fails there. The fix is `gh auth login`, then a fresh `gh repo clone` with `.env` copied across.
3. **Termux:Boot as a requirement.** It often won't install. Opening Termux once after a reboot must be enough, and it is.
4. **libass units.** Subtitle `FontSize`/`MarginV` in `force_style` are on a 288-line canvas, not pixels, and SRT alignment uses **legacy SSA numbers** (2 = bottom centre, 6 = top centre; *not* 8). Both shipped wrong at first.
5. **Stale render cache.** The scene cache key must include the renderer's source hash (`RENDERER_SOURCE` in `pipeline.py`), or renderer changes reuse old frames.
6. **Spoken length ≠ written length.** `Rp25.000` is read as five words. Estimate from `normalize_for_speech(...)`, never raw text.
7. **QA that passes broken video.** A fully black video once passed the black-frame check, and a video without audio crashed QA. `tests/test_media.py` guards both. Don't loosen them.
8. **External services from the dev sandbox.** Its network policy denies `deb.debian.org` and `api.elevenlabs.io`. Test providers against local stub servers (see `tests/`), and record live checks as NOT VERIFIED instead of "fixing" working code. The Docker build fails here for the same reason.
9. **Docker build in the dev sandbox.** Its network policy denies `deb.debian.org`, so the APEX image can't build there. That's the sandbox, not the Dockerfile; record it as NOT VERIFIED instead of "fixing" the Dockerfile.
10. **Headroom phones home by default.** `headroom proxy` uploads session summaries to Headroom Labs unless `HEADROOM_BEACON=off` (or `DO_NOT_TRACK=1`). Always start it with the beacon off.
11. **An admin check that fails open.** `if ADMIN_ID and user != ADMIN_ID` let anyone spend the owner's AI quota whenever `TELEGRAM_ADMIN_ID` was empty, and the old defaults also said `localhost` despite trap 1. Both shipped unnoticed because the bot had no tests. `tests/test_bot.py` now fails on either.
12. **Telegram timeouts on the phone.** python-telegram-bot gives each request 5 s and makes one startup attempt, so a slow mobile moment crashed the bot with `telegram.error.TimedOut` and runit restarted it in a loop. `build_app()` sets 30 s timeouts and `main()` passes `bootstrap_retries=-1`; `tests/test_bot.py` guards both. If `TimedOut` persists, test the network: `curl -m 20 https://api.telegram.org` (000 means Telegram is blocked on that network).
