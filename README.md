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

## Commands

- `/caption <brief>` — TikTok caption with hashtags
- `/idea <brief>` — TikTok video idea with hook, scenes and CTA
- `/hook <topic>` — 5 TikTok hooks (mystery, emotional, debate, funny, educational) for Cinta Beda Negara
- `/script <story>` — full TikTok script: hook → story → twist → payoff → question, with on-screen text, B-roll, music, caption and hashtags
- `/ping` — checks that the AI connection (OmniRoute or OpenAI) works
- `/help` — list commands

Never commit `.env`; it is ignored by git.
