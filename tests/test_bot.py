"""Tests for bot.py: the owner-only gate, the default gateway address, and route fallback.

Original request: the owner asked to fix the localhost default and the admin check that let anyone
use the bot when TELEGRAM_ADMIN_ID was empty, and to keep those fixes from coming back.
"""
import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import dotenv
import httpx
import pytest
from openai import APIConnectionError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ENV_VARS = ("TELEGRAM_ADMIN_ID", "OMNIROUTE_API_KEY", "OMNIROUTE_BASE_URL", "OMNIROUTE_MODEL",
            "OPENAI_API_KEY", "OPENAI_MODEL", "HEADROOM_BASE_URL")


@pytest.fixture
def load_bot(monkeypatch):
    """Import bot.py fresh with exactly the given env, ignoring any local .env file."""
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

    def _load(**env):
        for name in ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        sys.modules.pop("bot", None)
        return importlib.import_module("bot")
    return _load


def fake_update(user_id):
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id),
                           message=SimpleNamespace(reply_text=AsyncMock()))


def replies(update):
    return [c.args[0] for c in update.message.reply_text.await_args_list]


def test_omniroute_defaults_to_127_0_0_1(load_bot):
    bot = load_bot(OMNIROUTE_API_KEY="k")
    assert bot.OMNIROUTE_BASE_URL == "http://127.0.0.1:20128/v1"


@pytest.mark.parametrize("admin_id, user_id, expected", [
    ("", 42, False),          # unset: nobody, not everybody
    ("42", 42, True),
    ("42", 7, False),
    (" 42 ", 42, True),       # stray spaces in .env
])
def test_is_admin(load_bot, admin_id, user_id, expected):
    bot = load_bot(TELEGRAM_ADMIN_ID=admin_id)
    assert bot.is_admin(user_id) is expected


def test_unset_admin_refuses_and_shows_the_users_id(load_bot):
    bot = load_bot(OMNIROUTE_API_KEY="k")
    bot.chat = AsyncMock()
    update = fake_update(123456)
    asyncio.run(bot.generate(update, SimpleNamespace(args=[]), "task"))
    bot.chat.assert_not_awaited()
    assert "TELEGRAM_ADMIN_ID=123456" in replies(update)[0]


@pytest.mark.parametrize("handler", ["generate", "ping"])
def test_stranger_is_refused_when_admin_set(load_bot, handler):
    bot = load_bot(TELEGRAM_ADMIN_ID="42", OMNIROUTE_API_KEY="k")
    bot.chat = AsyncMock()
    update = fake_update(7)
    args = (update, SimpleNamespace(args=[])) + (("task",) if handler == "generate" else ())
    asyncio.run(getattr(bot, handler)(*args))
    bot.chat.assert_not_awaited()
    assert replies(update) == ["This assistant is private."]


def test_admin_gets_answer_split_at_4000_chars(load_bot):
    bot = load_bot(TELEGRAM_ADMIN_ID="42", OMNIROUTE_API_KEY="k")
    text = "x" * 4500
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    bot.chat = AsyncMock(return_value=("route", response))
    update = fake_update(42)
    asyncio.run(bot.generate(update, SimpleNamespace(args=[]), "task"))
    assert replies(update)[1:] == ["x" * 4000, "x" * 500]


def _client(result):
    create = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_chat_falls_back_only_on_connection_errors(load_bot):
    bot = load_bot(OMNIROUTE_API_KEY="k")
    down = APIConnectionError(request=httpx.Request("POST", "http://127.0.0.1:8765/v1"))
    bot.routes = [("Headroom", _client(down)), ("OmniRoute", _client("ok"))]
    assert asyncio.run(bot.chat(model="m", messages=[])) == ("OmniRoute", "ok")

    bot.routes = [("Headroom", _client(ValueError("bad request"))), ("OmniRoute", _client("ok"))]
    with pytest.raises(ValueError):
        asyncio.run(bot.chat(model="m", messages=[]))
