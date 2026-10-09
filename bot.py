import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID", "")

client = AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalamu'alaikum! 🌸 Welcome to LSKhan Jastip AI!\n\n"
        "Commands:\n"
        "/caption - Create a TikTok caption\n"
        "/idea - Get a content idea\n"
        "/help - Show commands"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE, task: str):
    if ADMIN_ID and str(update.effective_user.id) != ADMIN_ID:
        await update.message.reply_text("This assistant is private.")
        return
    if not client:
        await update.message.reply_text("OpenAI is not configured yet.")
        return
    prompt = "You are LSKhan Jastip's honest Indonesian content assistant. Never invent prices, stock, receipts, reviews, or delivery promises. Use warm natural Bahasa Indonesia. Task: " + task
    await update.message.reply_text("Sebentar ya 🌷 Aku sedang menyiapkan ide...")
    try:
        response = await client.responses.create(
            model="gpt-4.1-mini",
            input=prompt
        )
        await update.message.reply_text(response.output_text[:4000])
    except Exception:
        logging.exception("OpenAI request failed")
        await update.message.reply_text("Maaf, ada kendala. Coba lagi sebentar ya.")

async def caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = "Buat caption TikTok untuk jastip barang Thailand ke Indonesia, dengan 5-8 hashtag relevan. Brief: " + " ".join(context.args)
    await generate(update, context, task)

async def idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = "Buat satu ide video TikTok jastip LSKhan yang mudah direkam sendirian, lengkap dengan hook, adegan, dan CTA. Brief: " + " ".join(context.args)
    await generate(update, context, task)

def main():
    if not TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in .env")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("caption", caption))
    app.add_handler(CommandHandler("idea", idea))
    app.run_polling()

if __name__ == "__main__":
    main()
