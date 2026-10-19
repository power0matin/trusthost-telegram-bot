"""Authorization + language gate. Runs before every handler."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.keyboards.common import language_keyboard
from app.core.context import current_user_id
from app.core.logging import get_logger, log_event
from app.i18n import t
from app.services.container import Hub

log = get_logger("auth")


class AuthMiddleware(BaseMiddleware):
    def __init__(self, hub: Hub) -> None:
        self.hub = hub

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return None
        # Account data must never be rendered where other people could read it: private chats only.
        chat = event.chat if isinstance(event, Message) else (
            event.message.chat if isinstance(event, CallbackQuery) and event.message else None)
        if chat is not None and chat.type != "private":
            log_event(log, "non_private_chat_ignored", user=tg_user.id, chat_type=chat.type)
            return None
        if not self.hub.is_admin(tg_user.id):
            # No DB row, no API probing, no hint about configuration for strangers.
            lang = "fa" if (tg_user.language_code or "").startswith("fa") else "en"
            log_event(log, "unauthorized_access", user=tg_user.id)
            if isinstance(event, CallbackQuery):
                await event.answer(t(lang, "auth.denied"), show_alert=True)
            elif isinstance(event, Message):
                await event.answer(t(lang, "auth.denied"))
            return None

        token = current_user_id.set(tg_user.id)
        try:
            user = await self.hub.repo.get_or_create_user(tg_user.id)
            data["hub"] = self.hub
            data["user"] = user
            data["lang"] = user.language or self.hub.settings.default_language

            is_lang_choice = isinstance(event, CallbackQuery) and (event.data or "").startswith("lg:")
            if user.language is None and not is_lang_choice:
                text = t("en", "lang.choose")
                if isinstance(event, CallbackQuery):
                    await event.answer()
                    if isinstance(event.message, Message):
                        await event.message.answer(text, reply_markup=language_keyboard("s"))
                elif isinstance(event, Message):
                    await event.answer(text, reply_markup=language_keyboard("s"))
                return None

            if isinstance(event, CallbackQuery):
                try:  # stop the client spinner immediately; slow API calls follow
                    await event.answer()
                except Exception:
                    pass
            return await handler(event, data)
        finally:
            current_user_id.reset(token)
