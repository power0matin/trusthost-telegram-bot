from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import views
from app.bot.callbacks import Lang, Menu, Nav
from app.bot.handlers import billing, orders, servers, settings, tickets
from app.bot.keyboards.common import kb, main_menu, nav_row
from app.bot.ui import Event, fail, loading, show
from app.i18n import t
from app.services.container import Hub
from app.trusthost.exceptions import TrustHostError

router = Router(name="start")


async def show_home(event: Event, hub: Hub, lang: str, *, force: bool = False, new: bool = False) -> None:
    """Dashboard. A failing API still leaves the user with a working menu."""
    if isinstance(event, CallbackQuery):
        await loading(event, lang)
    try:
        dash = await hub.account.dashboard(force=force)
    except TrustHostError as exc:
        from app.i18n.errors import translate_exception
        await show(event, f"❌ {translate_exception(exc, lang).lstrip('❌ ').strip()}\n\n{t(lang, 'menu.title')}",
                   main_menu(lang), new=new)
        return
    await show(event, views.dashboard_text(lang, dash), main_menu(lang), new=new)


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await show_home(message, hub, lang)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await message.answer(t(lang, "cancelled"))
    await show_home(message, hub, lang)


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer(t(lang, "help.text"), reply_markup=kb(nav_row(lang)))


@router.callback_query(Nav.filter(F.a == "home"))
async def cb_home(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await show_home(cb, hub, lang)


@router.callback_query(Nav.filter(F.a == "cancel"))
async def cb_cancel(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await show_home(cb, hub, lang)


@router.callback_query(Nav.filter(F.a == "noop"))
async def cb_noop(cb: CallbackQuery) -> None:
    return None


@router.callback_query(Lang.filter())
async def cb_language(cb: CallbackQuery, callback_data: Lang, state: FSMContext, hub: Hub) -> None:
    if callback_data.code not in ("fa", "en"):
        return
    await hub.repo.set_language(cb.from_user.id, callback_data.code)
    lang = callback_data.code
    if callback_data.src == "t":
        await settings.show_settings(cb, lang)
    else:
        await state.clear()
        await show_home(cb, hub, lang)


@router.callback_query(Menu.filter())
async def cb_menu(cb: CallbackQuery, callback_data: Menu, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    a = callback_data.a
    if a == "srv":
        await servers.show_servers(cb, hub, lang)
    elif a == "order":
        await orders.show_groups(cb, hub, lang)
    elif a == "inv":
        await billing.show_invoices_menu(cb, lang)
    elif a == "wal":
        await billing.show_wallet(cb, hub, lang)
    elif a == "usage":
        await servers.show_servers(cb, hub, lang, mode="u")
    elif a == "support":
        await tickets.show_support_menu(cb, lang)
    elif a == "settings":
        await settings.show_settings(cb, lang)
    elif a == "refresh":
        await show_home(cb, hub, lang, force=True)


# ---- slash commands for the same screens (buttons remain the primary interface) -----------------
@router.message(Command("servers"))
async def cmd_servers(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await servers.show_servers(message, hub, lang)


@router.message(Command("usage"))
async def cmd_usage(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await servers.show_servers(message, hub, lang, mode="u")


@router.message(Command("orders"))
async def cmd_orders(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await orders.show_groups(message, hub, lang)


@router.message(Command("invoices"))
async def cmd_invoices(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await billing.show_invoices_menu(message, lang)


@router.message(Command("wallet"))
async def cmd_wallet(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await billing.show_wallet(message, hub, lang)


@router.message(Command("support"))
async def cmd_support(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await tickets.show_support_menu(message, lang)


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await settings.show_settings(message, lang)


@router.message(Command("health"))
async def cmd_health(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await settings.show_health(message, hub, lang)
