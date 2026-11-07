"""Notifications: Telegram Bot API and SMTP email, with per-user preferences and delivery tracking.

Config (environment, never the database):
  TELEGRAM_BOT_TOKEN                          bot token from @BotFather
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_SECURITY (starttls | ssl | none)
Per user (users table): telegram_chat_id, email, alert_prefs = {"<event>": ["telegram", "email"], ...}
Events: signal, execution, risk_warning, system_health, whale, news.
Every attempt is stored in `notifications` with status sent | failed | skipped and the error text.
A failed send is retried up to 3 times with backoff; it never blocks trading.
"""
from __future__ import annotations

import os
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape

import httpx

from .db import Store

EVENTS = ("signal", "execution", "risk_warning", "system_health", "whale", "news")
DEFAULT_PREFS = {"signal": ["telegram"], "execution": ["telegram", "email"], "risk_warning": ["telegram", "email"],
                 "system_health": ["email"], "whale": [], "news": []}

TEMPLATES = {
    "signal": ("Signal: {symbol} {side} ({strategy})", "Entry {entry}\nStop {stop}\nTarget {target}\nScore {score}\nData {source} @ {ts}"),
    "execution": ("Order {status}: {symbol} {qty}", "Exchange {exchange}{testnet}\nClient id {client_order_id}\nAvg price {avg_price}\n"
                  "Protection {protection}"),
    "risk_warning": ("Risk: {kind}", "{detail}"),
    "system_health": ("Health: {component} {state}", "{detail}"),
    "whale": ("Whale: {asset} {flow}", "{amount} {asset} (${amount_usd})\n{reference}"),
    "news": ("News: {title}", "{source} {published}\n{url}"),
}


class _Safe(dict):
    def __missing__(self, k):
        return "-"


def render(event: str, data: dict) -> tuple[str, str]:
    subj, body = TEMPLATES[event]
    return subj.format_map(_Safe(data))[:200], body.format_map(_Safe(data))


class SendError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str | None = None, http: httpx.Client | None = None, base: str = "https://api.telegram.org"):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.http = http or httpx.Client(timeout=10)
        self.base = base

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def send(self, chat_id: str, subject: str, body: str) -> None:
        if not self.token:
            raise SendError("TELEGRAM_BOT_TOKEN not set")
        text = f"<b>{escape(subject)}</b>\n{escape(body)}"
        try:
            r = self.http.post(f"{self.base}/bot{self.token}/sendMessage",
                               json={"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML", "disable_web_page_preview": True})
        except httpx.HTTPError as e:
            raise SendError(f"telegram: {type(e).__name__}") from e  # message would include the token-bearing URL
        d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or not d.get("ok"):
            raise SendError(f"telegram: HTTP {r.status_code} {d.get('description', '')}".strip())

    def check(self) -> dict:
        if not self.token:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}
        try:
            r = self.http.get(f"{self.base}/bot{self.token}/getMe")
            d = r.json()
            return {"ok": bool(d.get("ok")), "bot": d.get("result", {}).get("username"), "error": d.get("description")}
        except (httpx.HTTPError, ValueError) as e:
            return {"ok": False, "error": type(e).__name__}


@dataclass
class SMTPConfig:
    host: str
    port: int
    user: str | None
    password: str | None
    sender: str
    security: str = "starttls"

    @classmethod
    def from_env(cls) -> "SMTPConfig | None":
        if not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM"):
            return None
        return cls(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"),
                   os.environ["SMTP_FROM"], os.getenv("SMTP_SECURITY", "starttls"))


class Email:
    def __init__(self, cfg: SMTPConfig | None = None):
        self.cfg = cfg if cfg is not None else SMTPConfig.from_env()

    @property
    def configured(self) -> bool:
        return self.cfg is not None

    def send(self, to: str, subject: str, body: str) -> None:
        c = self.cfg
        if not c:
            raise SendError("SMTP_HOST / SMTP_FROM not set")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = c.sender, to, subject
        msg.set_content(body + "\n\n-- Promovent (automated message)")
        try:
            if c.security == "ssl":
                s = smtplib.SMTP_SSL(c.host, c.port, timeout=10, context=ssl.create_default_context())
            else:
                s = smtplib.SMTP(c.host, c.port, timeout=10)
                if c.security == "starttls":
                    s.starttls(context=ssl.create_default_context())
            with s:
                if c.user:
                    s.login(c.user, c.password or "")
                s.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            raise SendError(f"smtp: {type(e).__name__}: {e}") from e


class Notifier:
    def __init__(self, store: Store, telegram: Telegram | None = None, email: Email | None = None,
                 retries: int = 3, sleep=time.sleep):
        self.store, self.tg, self.mail = store, telegram or Telegram(), email or Email()
        self.retries, self.sleep = retries, sleep

    def status(self) -> dict:
        return {"telegram": "configured" if self.tg.configured else "missing TELEGRAM_BOT_TOKEN",
                "email": "configured" if self.mail.configured else "missing SMTP_HOST/SMTP_FROM"}

    def notify(self, event: str, data: dict, users: list[dict]) -> list[dict]:
        if event not in EVENTS:
            raise ValueError(event)
        subject, body = render(event, data)
        results = []
        for u in users:
            prefs = (u.get("alert_prefs") or {}).get(event, DEFAULT_PREFS[event])
            for ch in prefs:
                target = u.get("telegram_chat_id") if ch == "telegram" else u.get("email") if ch == "email" else None
                status, err, attempts = "skipped", None, 0
                if not target:
                    err = f"user has no {ch} address"
                elif (ch == "telegram" and not self.tg.configured) or (ch == "email" and not self.mail.configured):
                    err = self.status()[ch]
                else:
                    for attempts in range(1, self.retries + 1):
                        try:
                            (self.tg.send if ch == "telegram" else self.mail.send)(target, subject, body)
                            status, err = "sent", None
                            break
                        except SendError as e:
                            status, err = "failed", str(e)
                            if attempts < self.retries:
                                self.sleep(2 ** attempts)
                nid = self.store.add_notification(user_id=u.get("id"), channel=ch, event=event, subject=subject, body=body,
                                                  status=status, error=err, attempts=attempts)
                results.append({"id": nid, "user": u.get("username"), "channel": ch, "status": status, "error": err})
        return results
