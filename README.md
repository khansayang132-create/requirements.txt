# LSKhan Telegram AI Bot

Telegram bot that writes TikTok captions and content ideas. AI requests go through
[OmniRoute](https://github.com/diegosouzapw/OmniRoute) (an OpenAI-compatible gateway),
or directly to OpenAI if no OmniRoute key is set.

## Setup

1. Install and start OmniRoute on your machine:
   ```
   omniroute
   ```
   Dashboard and API run on `http://127.0.0.1:20128`. Create an API key in the dashboard
   and connect at least one provider.
2. Install the bot's dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Copy the env template and fill it in:
   ```
   cp .env.example .env
   ```
   - `TELEGRAM_BOT_TOKEN` — from @BotFather
   - `TELEGRAM_ADMIN_ID` — your Telegram user ID (required: until it is set, the bot refuses AI commands and replies with your ID so you can copy it in)
   - `OMNIROUTE_API_KEY` — your OmniRoute key
   - `OMNIROUTE_BASE_URL` — leave as `http://127.0.0.1:20128/v1` unless OmniRoute runs elsewhere
   - `OMNIROUTE_MODEL` — `auto` lets OmniRoute pick; or set a specific model
4. Run the bot:
   ```
   python bot.py
   ```

## Optional: Headroom (context compression)

[Headroom](https://pypi.org/project/headroom-ai/) is an OpenAI-compatible proxy that compresses
prompts before they reach the gateway. The bot uses it when `HEADROOM_BASE_URL` is set, and falls
back to OmniRoute directly if Headroom isn't running, so stopping it never breaks the bot.

Start Headroom on port 8765, forwarding to OmniRoute:
```
HEADROOM_BEACON=off OPENAI_TARGET_API_URL=http://127.0.0.1:20128/v1 headroom proxy --port 8765
```
`HEADROOM_BEACON=off` stops Headroom's default upload of session summaries to Headroom Labs.

Then in `.env`:
```
HEADROOM_BASE_URL=http://127.0.0.1:8765/v1
```
`/ping` shows which route answered, for example `Headroom http://127.0.0.1:8765/v1`, or
`http://127.0.0.1:20128/v1 (fallback: Headroom … unreachable)`.

## Run 24/7 on an Android phone (Termux)

In Termux, inside the bot folder:
```
git pull
bash termux/install.sh            # bot + OmniRoute in the background
```
It stops any copies you started by hand, runs both in the background, restarts them if they
crash. Then, once:
1. Android **Settings → Apps → Termux → Battery → Unrestricted**.
2. Keep the Termux notification (don't swipe it away or tap Exit).

After the phone restarts, **open Termux once** and the bot and OmniRoute start again by themselves.
(Optional: the **Termux:Boot** app does that step for you, but it must come from the same place
as your Termux, and some phones can't install it. It's not required.)

- Check: `bash termux/install.sh status`
- Logs: `bash termux/install.sh logs`
- After editing `.env`: run `bash termux/install.sh` again
- Stop for good: `bash termux/install.sh uninstall`

## Publish the website on your phone (port 8080)

This puts a website running on the phone (for example `http://localhost:8080`) at a fixed public
address, password protected, running 24/7 next to the bot.

1. Create a free account at [ngrok](https://dashboard.ngrok.com). Copy your **authtoken**, and under
   **Domains** copy your free fixed domain (like `name.ngrok-free.app`).
2. In `.env`:
   ```
   NGROK_AUTHTOKEN=your-token
   SITE_DOMAIN=name.ngrok-free.app
   SITE_PORT=8080
   SITE_AUTH=you:a-long-password
   ```
3. Run `bash termux/install.sh site`. The site is now at `https://name.ngrok-free.app`, and the browser
   asks for that username and password.

To let Claude's cloud sessions use it: in the cloud environment's settings, add the domain under
**Allowed domains**, and add `SITE_URL=https://name.ngrok-free.app` and `SITE_AUTH=you:a-long-password`
as environment secrets. Every session can then run `scripts/site.sh check`.

## Run 24/7 (Linux)

Make the bot start at boot, restart itself if it crashes, and keep running after you log out:
```
cd ~/path/to/this/repo
sudo bash service/install.sh                  # bot only
sudo bash service/install.sh --with-omniroute # bot + OmniRoute as services
```
If you use `--with-omniroute`, first stop any OmniRoute you started by hand (Ctrl+C in its window),
so the service can use port 20128.

- Logs: `journalctl -u lskhan-bot -f` (and `journalctl -u lskhan-omniroute -f`)
- After editing `.env`: `sudo systemctl restart lskhan-bot`
- Stop for good: `sudo bash service/install.sh uninstall`

## Commands

- `/caption <brief>` — TikTok caption with hashtags
- `/idea <brief>` — TikTok video idea with hook, scenes and CTA
- `/hook <topic>` — 5 TikTok hooks (mystery, emotional, debate, funny, educational) for Cinta Beda Negara
- `/script <story>` — full TikTok script: hook → story → twist → payoff → question, with on-screen text, B-roll, music, caption and hashtags
- `/ping` — checks that the AI connection (OmniRoute or OpenAI) works
- `/help` — list commands

Never commit `.env`; it is ignored by git.

## Engineering agency (checks for this repo)

`agency/` runs the repo's own checks as a team of specialist roles: tests, lint, secret scan,
dependency and vulnerability checks. It can also make code changes on a separate branch, test that
branch and push it, always asking you first. Each result is checked by a second role, and the run
ends with a report.
```
python -m agency run health      # needs: pip install -r requirements.txt -r apex/requirements.txt pytest
python -m agency dashboard       # http://127.0.0.1:8790, read-only
```
See [`agency/README.md`](agency/README.md) for how it works and [`agency/STATUS.md`](agency/STATUS.md)
for what has been verified.
