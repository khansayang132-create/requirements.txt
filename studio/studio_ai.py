"""AI calls for LSKhan Studio.

Everything LSKhan-specific comes from bot.py, so the app and the Telegram bot can't drift:
CINTA_PERSONA (the content rules), hook_task / script_task (the prompts), and the AI routes
(Headroom → OmniRoute or OpenAI, same .env, same fallback). bot.py's client is async; it runs
on one long-lived event loop in a background thread because its HTTP pool is bound to the loop
that first used it.
"""
import asyncio
import hmac
import logging
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot  # noqa: E402  (loads the repo's .env; does not start the Telegram bot)

MAX_TOPIC = 2000
TIMEOUT_S = 180

# jaclang 0.16.7 binds its server to 0.0.0.0 whatever --host says, so anyone on the same Wi-Fi
# can reach the walkers. Every AI call needs this code. Like TELEGRAM_ADMIN_ID, it fails closed:
# with STUDIO_ACCESS_CODE unset nobody passes.
ACCESS_CODE = os.getenv("STUDIO_ACCESS_CODE", "").strip()
LOCKED = "Studio terkunci. Isi STUDIO_ACCESS_CODE di .env lalu jalankan ulang Studio."
WRONG = "Kode akses salah."

def access_error(code: str) -> str:
    """Empty string when the code is right, else the reason. Wrong guesses are slowed down."""
    if not ACCESS_CODE:
        return LOCKED
    if not code:
        return "Masukkan kode akses."
    if hmac.compare_digest(code.encode(), ACCESS_CODE.encode()):
        return ""
    time.sleep(1)
    return WRONG

# The ten content angles from the LSKhan editor brief. Rotating them keeps videos fresh.
ANGLES = {
    "emosional": "Emosional: perasaan yang jujur, jeda yang bermakna, musik lembut.",
    "kontroversial": "Kontroversial: pertanyaan yang bikin orang beda pendapat, tanpa kebencian.",
    "misteri": "Misteri: buka dengan sesuatu yang belum terjawab, jawab di akhir.",
    "edukasi": "Edukasi: poin praktis yang bisa langsung dipakai penonton.",
    "lucu": "Lucu: momen budaya yang kocak, timing komedi, suami tidak dibuat bodoh.",
    "budaya": "Budaya: perbedaan kecil Indonesia × Pakistan yang awalnya membingungkan.",
    "keluarga": "Keluarga: reaksi dan dinamika keluarga, tetap hormat ke semua pihak.",
    "realita": "Realita: yang tidak terlihat di foto pernikahan beda negara.",
    "debat": "Debat: dua pilihan yang sama-sama masuk akal, ajak penonton memilih.",
    "islami": "Islami: tanggung jawab dan nilai pernikahan, tenang dan penuh hormat.",
}

def caption_task(topic: str) -> str:
    return (
        "Buat 3 pilihan caption TikTok yang singkat dan bikin penasaran (contoh gaya: "
        "'Ternyata menikah beda negara bukan cuma tentang cinta… 🌏💍'). Untuk tiap pilihan beri "
        "4-7 hashtag yang benar-benar sesuai topik (misal #NikahBedaNegara #NikahBedaBudaya "
        "#IndonesiaPakistan #MixedMarriage #KisahCinta #FYP), jangan spam hashtag yang tidak nyambung. "
        "Topik/cerita: " + (topic.strip() or bot.DEFAULT_TOPIC)
    )

def series_task(topic: str) -> str:
    return (
        "Pecah cerita ini menjadi series TikTok 3-5 part. Untuk tiap part beri: judul part, hook 1-2 "
        "detik pertama, inti cerita part itu, dan alasan penonton ingin menonton part berikutnya. "
        "Tiap part harus tetap menarik walau ditonton sendiri. Jangan menambah kejadian serius yang "
        "tidak ada di cerita. Cerita: " + (topic.strip() or bot.DEFAULT_TOPIC)
    )

TASKS = {"hook": bot.hook_task, "script": bot.script_task, "caption": caption_task, "series": series_task}

_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, name="studio-ai", daemon=True).start()

def status(code: str) -> dict:
    """Is the code right, and is an AI route configured? Spends no AI call."""
    error = access_error(code)
    return {"access": not error, "error": error, "locked": not ACCESS_CODE, "ai": bool(bot.routes)}

def generate(kind: str, topic: str, angle: str, code: str) -> dict:
    """Returns {"ok": True, "text": ...} or {"ok": False, "error": <message for the owner>}."""
    error = access_error(code)
    if error:
        return {"ok": False, "error": error}
    if kind not in TASKS:
        return {"ok": False, "error": "Jenis konten tidak dikenal."}
    if len(topic) > MAX_TOPIC:
        return {"ok": False, "error": f"Ceritanya terlalu panjang (maks {MAX_TOPIC} huruf)."}
    if not bot.routes:
        return {"ok": False, "error": "AI belum diatur. Isi OMNIROUTE_API_KEY atau OPENAI_API_KEY di .env."}
    task = TASKS[kind](topic)
    if angle in ANGLES:
        task += " Arah konten video ini: " + ANGLES[angle]
    messages = [{"role": "user", "content": bot.CINTA_PERSONA + " Task: " + task}]
    try:
        future = asyncio.run_coroutine_threadsafe(bot.chat(model=bot.MODEL, messages=messages), _loop)
        _, response = future.result(timeout=TIMEOUT_S)
    except Exception:
        logging.exception("Studio AI request failed")
        return {"ok": False, "error": "Maaf, AI sedang tidak bisa dihubungi. Cek OmniRoute lalu coba lagi."}
    return {"ok": True, "text": (response.choices[0].message.content or "").strip()}
