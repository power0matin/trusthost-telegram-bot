"""Last-resort handlers: stray text outside any flow, and global error handling."""
from __future__ import annotations

from aiogram import Router
from aiogram.types import ErrorEvent, Message

from app.bot.keyboards.common import main_menu
from app.core.guard import OperationInProgress
from app.core.logging import get_logger
from app.i18n import t

router = Router(name="fallback")
log = get_logger("bot.errors")


@router.message()
async def stray_message(message: Message, lang: str) -> None:
    await message.answer(t(lang, "fallback.hint"), reply_markup=main_menu(lang))


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    exc = event.exception
    if isinstance(exc, OperationInProgress):
        return True  # duplicate click while the first one is still running – silently ignore
    log.error("unhandled_update_error", exc_info=exc)  # redacted by the logging filter
    update = event.update
    target = update.message or (update.callback_query.message if update.callback_query else None)
    user = update.message.from_user if update.message else (update.callback_query.from_user if update.callback_query else None)
    lang = "fa" if user and (user.language_code or "").startswith("fa") else "en"
    try:
        if isinstance(target, Message):
            await target.answer(t(lang, "err.generic"))
    except Exception:
        pass
    return True
