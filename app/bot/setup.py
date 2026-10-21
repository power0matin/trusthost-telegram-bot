from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from app.bot.handlers import (
    billing, fallback, orders, renewal, servers, settings, start, tickets, topup, wallet,
)
from app.bot.middlewares.auth import AuthMiddleware
from app.i18n import t
from app.services.container import Hub

COMMANDS = ("start", "menu", "servers", "orders", "invoices", "wallet", "usage", "support", "settings", "help", "cancel")


def _detach(router: Router) -> Router:
    """Handler routers are module-level; allow building several dispatchers (tests, hot restarts)."""
    router._parent_router = None  # noqa: SLF001
    return router


def build_dispatcher(hub: Hub) -> Dispatcher:
    """FSM data lives in memory only: order drafts (incl. the root password) never touch disk."""
    dp = Dispatcher(storage=MemoryStorage())
    auth = AuthMiddleware(hub)
    dp.message.outer_middleware(auth)
    dp.callback_query.outer_middleware(auth)
    # Order matters: commands (start) before state-bound text handlers, fallback last.
    dp.include_routers(*(_detach(m.router) for m in (start, servers, topup, wallet, renewal, billing, orders,
                                                       tickets, settings, fallback)))
    return dp


async def set_bot_commands(bot: Bot) -> None:
    """Command *syntax* stays English; only the descriptions are localized."""
    for lang, code in (("en", None), ("fa", "fa")):
        cmds = [BotCommand(command=c, description=t(lang, f"cmd.{c}")) for c in COMMANDS]
        await bot.set_my_commands(cmds, scope=BotCommandScopeDefault(), language_code=code)
