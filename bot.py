import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from openai import APIConnectionError, AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID", "").strip()

# OmniRoute is an OpenAI-compatible gateway; when its key is set, route through it.
OMNIROUTE_KEY = os.getenv("OMNIROUTE_API_KEY", "")
OMNIROUTE_BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")

# Headroom (optional) is a context-compression proxy in front of the same gateway. When
# HEADROOM_BASE_URL is set, requests go through it first and fall back to the direct route
# only if Headroom itself can't be reached, so a stopped proxy never takes the bot down.
HEADROOM_BASE_URL = os.getenv("HEADROOM_BASE_URL", "")

routes = []  # (label, client), tried in order
if OMNIROUTE_KEY:
    if HEADROOM_BASE_URL:
        routes.append((f"Headroom {HEADROOM_BASE_URL}", AsyncOpenAI(api_key=OMNIROUTE_KEY, base_url=HEADROOM_BASE_URL, max_retries=0)))
    routes.append((OMNIROUTE_BASE_URL, AsyncOpenAI(api_key=OMNIROUTE_KEY, base_url=OMNIROUTE_BASE_URL)))
    MODEL = os.getenv("OMNIROUTE_MODEL", "auto")
elif OPENAI_KEY:
    if HEADROOM_BASE_URL:
        routes.append((f"Headroom {HEADROOM_BASE_URL}", AsyncOpenAI(api_key=OPENAI_KEY, base_url=HEADROOM_BASE_URL, max_retries=0)))
    routes.append(("OpenAI", AsyncOpenAI(api_key=OPENAI_KEY)))
    MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
else:
    MODEL = ""
client = routes[0][1] if routes else None

async def chat(**kwargs):
    """Send a chat completion along the first reachable route. Returns (route label, response)."""
    for i, (label, c) in enumerate(routes):
        try:
            return label, await c.chat.completions.create(**kwargs)
        except APIConnectionError:
            if i == len(routes) - 1:
                raise
            logging.warning("%s unreachable, falling back to %s", label, routes[i + 1][0])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalamu'alaikum! 🌸 Welcome to LSKhan Jastip AI!\n\n"
        "Commands:\n"
        "/caption - Create a TikTok caption\n"
        "/idea - Get a content idea\n"
        "/hook - 5 TikTok hooks for Cinta Beda Negara\n"
        "/script - Full TikTok script for Cinta Beda Negara\n"
        "/ping - Check the AI connection\n"
        "/help - Show commands"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

JASTIP_PERSONA = "You are LSKhan Jastip's honest Indonesian content assistant. Never invent prices, stock, receipts, reviews, or delivery promises. Use warm natural Bahasa Indonesia."

# Persona for LSKhan 🌏💞 Cinta Beda Negara (Indonesia × Pakistan mixed-marriage) TikTok content.
CINTA_PERSONA = (
    "You are the TikTok content writer for LSKhan 🌏💞 Cinta Beda Negara, a real Indonesian wife and "
    "Pakistani husband sharing their cross-border Islamic marriage: culture differences, family, "
    "long distance, funny moments and unexpected realities. Write in warm, natural Bahasa Indonesia. "
    "Goal: watch time, completion, comments, shares and follows. "
    "Rules: the first 1-2 seconds must create curiosity with a statement, question, surprise or mystery, "
    "never a slow greeting like 'Hello guys hari ini aku mau cerita'. "
    "Curiosity without lying, emotion without overacting, no fake drama, never invent serious events. "
    "Never make the husband look stupid or the Indonesian wife look cruel. "
    "Keep Islamic and family topics respectful, not cheap clickbait. "
    "Any ending question must connect naturally to the story."
)

def is_admin(user_id) -> bool:
    """Only the owner may spend AI calls. With TELEGRAM_ADMIN_ID unset nobody passes, so a fresh
    install never serves strangers on the owner's quota."""
    return bool(ADMIN_ID) and str(user_id) == ADMIN_ID

async def allowed(update: Update) -> bool:
    """Gate for every command that spends AI calls. Replies with the reason when it refuses."""
    user_id = update.effective_user.id
    if is_admin(user_id):
        return True
    if not ADMIN_ID:
        await update.message.reply_text(
            f"This bot is locked until TELEGRAM_ADMIN_ID is set. Your Telegram ID is {user_id}: "
            f"put TELEGRAM_ADMIN_ID={user_id} in .env and restart the bot."
        )
    else:
        await update.message.reply_text("This assistant is private.")
    return False

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE, task: str, persona: str = JASTIP_PERSONA):
    if not await allowed(update):
        return
    if not client:
        await update.message.reply_text("AI is not configured yet. Set OMNIROUTE_API_KEY or OPENAI_API_KEY.")
        return
    prompt = persona + " Task: " + task
    await update.message.reply_text("Sebentar ya 🌷 Aku sedang menyiapkan ide...")
    try:
        _, response = await chat(model=MODEL, messages=[{"role": "user", "content": prompt}])
        text = response.choices[0].message.content or ""
        # Telegram caps messages at 4096 chars; send long scripts in parts.
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i + 4000])
    except Exception:
        logging.exception("AI request failed")
        await update.message.reply_text("Maaf, ada kendala. Coba lagi sebentar ya.")

async def caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = "Buat caption TikTok untuk jastip barang Thailand ke Indonesia, dengan 5-8 hashtag relevan. Brief: " + " ".join(context.args)
    await generate(update, context, task)

async def idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = "Buat satu ide video TikTok jastip LSKhan yang mudah direkam sendirian, lengkap dengan hook, adegan, dan CTA. Brief: " + " ".join(context.args)
    await generate(update, context, task)

def brief_or_default(context: ContextTypes.DEFAULT_TYPE) -> str:
    brief = " ".join(context.args).strip()
    return brief or "Pilih sendiri satu topik segar (emosional, lucu, budaya, keluarga, edukasi, debat, atau Islami) tentang nikah beda negara Indonesia × Pakistan."

async def hook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = (
        "Buat 5 hook TikTok (kalimat pembuka 1-2 detik pertama) yang berbeda gaya: misteri, emosional, "
        "kontroversial/debat, lucu, dan edukasi. Untuk tiap hook beri: kalimat yang diucapkan, teks di layar "
        "(singkat, kata kunci huruf kapital seperti NIKAH BEDA NEGARA / ORANG PAKISTAN / TERNYATA...), "
        "dan satu baris kenapa hook ini membuat orang berhenti scroll. Topik: " + brief_or_default(context)
    )
    await generate(update, context, task, CINTA_PERSONA)

async def script(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = (
        "Buat naskah video TikTok 15-35 detik (boleh sampai 60 detik hanya jika ceritanya memang butuh). "
        "Struktur: HOOK → CERITA → KETEGANGAN/TWIST → PAYOFF → PERTANYAAN. Untuk tiap bagian tulis: "
        "perkiraan detik, kalimat yang diucapkan, teks di layar (singkat), dan visual/B-roll yang relevan "
        "(bandara, keluarga, makanan, pakaian tradisional, dokumen nikah, dll., jangan stok acak). "
        "Lalu beri: saran musik/suara sesuai emosi, pertanyaan penutup alami untuk komentar, "
        "caption singkat yang bikin penasaran, dan 4-7 hashtag relevan (misal #NikahBedaNegara "
        "#IndonesiaPakistan #MixedMarriage). Jika cerita cocok dijadikan series, sarankan Part 2. "
        "Topik/cerita: " + brief_or_default(context)
    )
    await generate(update, context, task, CINTA_PERSONA)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await allowed(update):
        return
    if not client:
        await update.message.reply_text("AI is not configured yet. Set OMNIROUTE_API_KEY or OPENAI_API_KEY.")
        return
    target = " → ".join(label for label, _ in routes)
    try:
        target, response = await chat(model=MODEL, messages=[{"role": "user", "content": "Reply with: OK"}],
                                      max_tokens=5)
        if target != routes[0][0]:
            target += f" (fallback: {routes[0][0]} unreachable)"
        reply = (response.choices[0].message.content or "").strip()
        await update.message.reply_text(f"✅ Connected to {target} (model: {response.model or MODEL}). Reply: {reply}")
    except Exception as e:
        logging.exception("AI ping failed")
        await update.message.reply_text(f"❌ Could not reach {target}: {type(e).__name__}")

# Phone networks are slow and drop out. The library gives each Telegram request 5 s and makes one
# startup attempt, so a slow moment crashed the bot with TimedOut. Allow 30 s, and keep retrying startup.
TELEGRAM_TIMEOUT = 30

def build_app() -> Application:
    app = (
        Application.builder().token(TOKEN)
        .connect_timeout(TELEGRAM_TIMEOUT).read_timeout(TELEGRAM_TIMEOUT).write_timeout(TELEGRAM_TIMEOUT)
        .get_updates_connect_timeout(TELEGRAM_TIMEOUT).get_updates_read_timeout(TELEGRAM_TIMEOUT)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("caption", caption))
    app.add_handler(CommandHandler("idea", idea))
    app.add_handler(CommandHandler("hook", hook))
    app.add_handler(CommandHandler("script", script))
    app.add_handler(CommandHandler("ping", ping))
    return app

def main():
    if not TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in .env")
    build_app().run_polling(bootstrap_retries=-1)  # -1: retry startup until Telegram is reachable

if __name__ == "__main__":
    main()
