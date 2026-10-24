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

## LSKhan Studio (app on the phone)

A phone web app for hooks, scripts (naskah), captions and series plans, plus the 10-point check
before uploading. It writes with the same rules and AI connection as the bot (`CINTA_PERSONA`,
OmniRoute). Built with [jac-shadcn](https://github.com/jaseci-labs/jac-shadcn) (`studio/`).

In Termux, inside the bot folder (OmniRoute must be running, as for the bot):
```
git pull && bash studio/run.sh setup && bash studio/run.sh
```
Then open **http://127.0.0.1:8000** in the phone's browser (Chrome menu → **Add to Home screen**
puts it next to your apps; Termux must still be running it). The first start makes an access code
in `.env`; see it with `grep STUDIO_ACCESS_CODE .env` and type it in once. The phone remembers it
("Kunci" forgets it). Studio refuses every AI request without the right code, because other
devices on the same Wi-Fi can reach the port. Stop it with Ctrl+C.

Changed the app's code? Rebuild the page on a computer (`pip install jac-client==0.3.25`,
`bash studio/run.sh setup`, then `bash studio/build.sh`) and commit `studio/prebuilt/`; the phone
can't build it.

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
