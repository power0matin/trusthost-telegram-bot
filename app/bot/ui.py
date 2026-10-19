"""Shared UI plumbing: message editing, loading states, error screens."""
from __future__ import annotations

import html
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot.keyboards.common import error_keyboard
from app.core.logging import get_logger, log_event
from app.i18n import t
from app.i18n.errors import translate_exception
from app.trusthost.exceptions import TrustHostError, TrustHostInsufficientCreditError

log = get_logger("ui")
Event = Message | CallbackQuery


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


async def show(event: Event, text: str, markup: InlineKeyboardMarkup | None = None, *,
               new: bool = False) -> Message | None:
    """Edit the current message in place when possible (keeps the chat clean); otherwise send a new one."""
    if isinstance(event, CallbackQuery):
        msg = event.message
        if not new and isinstance(msg, Message):
            try:
                res = await msg.edit_text(text, reply_markup=markup)
                return res if isinstance(res, Message) else msg
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc).lower():
                    return msg
                log_event(log, "edit_failed_sending_new", error=str(exc)[:80])
        if isinstance(msg, Message):
            return await msg.answer(text, reply_markup=markup)
        return None
    return await event.answer(text, reply_markup=markup)


async def loading(event: Event, lang: str, key: str = "loading") -> None:
    """Immediate feedback before a slow API call (only when we can edit the message)."""
    if isinstance(event, CallbackQuery) and isinstance(event.message, Message):
        try:
            await event.message.edit_text(t(lang, key), reply_markup=None)
        except TelegramBadRequest:
            pass
    elif isinstance(event, Message):
        pass  # a fresh message will be sent with the result


async def fail(event: Event, lang: str, exc: BaseException, back: CallbackData | None = None, *,
               hub: Any = None) -> None:
    """Friendly localized error that keeps the user's navigation context (Back + Home).

    On HTTP 402 the wallet top-up URL (from GET /wallet) is attached when available.
    """
    if isinstance(exc, TrustHostError):
        text = "❌ " + translate_exception(exc, lang).lstrip("❌ ").strip()
        log_event(log, "user_facing_error", error=getattr(exc, "code", type(exc).__name__))
    else:
        text = t(lang, "err.generic")
    url = None
    if hub is not None and isinstance(exc, TrustHostInsufficientCreditError):
        try:
            url = (await hub.billing.wallet()).add_funds_url
        except Exception:
            url = None
    await show(event, text, error_keyboard(lang, back, url))
