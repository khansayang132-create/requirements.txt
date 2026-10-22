# LSKhan Telegram AI Bot

Telegram bot that writes TikTok captions and content ideas. AI requests go through
[OmniRoute](https://github.com/diegosouzapw/OmniRoute) (an OpenAI-compatible gateway),
or directly to OpenAI if no OmniRoute key is set.

## Setup

1. Install and start OmniRoute on your machine:
   ```
   omniroute
   ```
   Dashboard and API run on `http://localhost:20128`. Create an API key in the dashboard
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
   - `TELEGRAM_ADMIN_ID` — your Telegram user ID (optional; makes the bot private)
   - `OMNIROUTE_API_KEY` — your OmniRoute key
   - `OMNIROUTE_BASE_URL` — leave as `http://localhost:20128/v1` unless OmniRoute runs elsewhere
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

### Experimental: Headroom on the phone

```
bash termux/install.sh --with-headroom
```
Builds Headroom on the phone and runs it as a third background service on `127.0.0.1:8765`, in
front of OmniRoute, and sets `HEADROOM_BASE_URL` in `.env` (unless you already set it).
Headroom has no Android builds, so this compiles about ten packages: expect **1-3 hours** and
**about 4 GB free space** while building. Keep Termux open and the phone charging; if it stops,
run the same command again and it continues.

If the build fails, the bot is still installed without Headroom, and the last lines of the build
log are shown (full log: `~/.lskhan-headroom/build.log`). Once built, later re-runs keep it on.

- Check: `bash termux/install.sh status` (also says whether Headroom answers)
- Logs: `bash termux/install.sh logs headroom`
- `uninstall` stops it but keeps the build. To free the space: `rm -rf ~/.lskhan-headroom`

This only helps the bot. It does not connect Headroom to Claude Code sessions, which run their own.

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
