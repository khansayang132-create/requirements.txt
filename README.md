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

## Run 24/7 on an Android phone (Termux)

In Termux, inside the bot folder:
```
git pull
bash termux/install.sh            # bot + OmniRoute in the background
```
It stops any copies you started by hand, runs both in the background, restarts them if they
crash, and starts them again after the phone reboots. Then, once:
1. Install the **Termux:Boot** app (same place you got Termux, e.g. F-Droid) and open it once.
2. Android **Settings → Apps → Termux → Battery → Unrestricted**.
3. Keep the Termux notification (don't swipe it away or tap Exit).

- Check: `bash termux/install.sh status`
- Logs: `bash termux/install.sh logs`
- After editing `.env`: run `bash termux/install.sh` again
- Stop for good: `bash termux/install.sh uninstall`

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
