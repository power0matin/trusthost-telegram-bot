from __future__ import annotations

from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.callbacks import Pref
from app.bot.keyboards.common import language_keyboard
from app.bot.keyboards.settings import back_to_settings_kb, health_kb, notifications_kb, settings_kb
from app.bot.ui import Event, esc, loading, show
from app.core.formatting import Fmt
from app.i18n import t
from app.services.container import Hub

router = Router(name="settings")


async def show_settings(event: Event, lang: str) -> None:
    await show(event, f"⚙️ <b>{t(lang, 'set.title')}</b>", settings_kb(lang))


async def show_health(event: Event, hub: Hub, lang: str) -> None:
    await loading(event, lang)
    report = await hub.health.check()
    f = Fmt(lang)
    ok = lambda v: "✅ OK" if v else "❌ " + t(lang, "health.fail")  # noqa: E731
    host = urlparse(hub.settings.trusthost_base_url).netloc
    rows = [f"ℹ️ <b>{t(lang, 'health.title')}</b>", "",
            f"Telegram: {ok(report.telegram_ok)}",
            f"{t(lang, 'health.database')}: {ok(report.database_ok)}",
            f"TrustHost API: {ok(report.api_ok)}" + (f" ({esc(report.api_error_code)})" if report.api_error_code else ""),
            f"{t(lang, 'health.response_time')}: {report.api_ms} ms", "",
            f"{t(lang, 'health.endpoint')}: <code>{esc(host)}</code>",
            f"{t(lang, 'health.credentials')}: ✅ {t(lang, 'health.configured')}",
            f"{t(lang, 'health.poll')}: {f.int(hub.settings.notification_poll_minutes)} {t(lang, 'health.minutes')}",
            f"{t(lang, 'health.last_check')}: {f.digits(report.checked_at)}"]
    await show(event, "\n".join(rows), health_kb(lang))


@router.callback_query(Pref.filter(F.a == "menu"))
async def cb_menu(cb: CallbackQuery, lang: str) -> None:
    await show_settings(cb, lang)


@router.callback_query(Pref.filter(F.a == "lang"))
async def cb_language(cb: CallbackQuery, lang: str) -> None:
    await show(cb, t(lang, "lang.choose"), language_keyboard("t"))


@router.callback_query(Pref.filter(F.a == "notif"))
async def cb_notifications(cb: CallbackQuery, hub: Hub, lang: str) -> None:
    user = await hub.repo.get_or_create_user(cb.from_user.id)
    await show(cb, f"🔔 <b>{t(lang, 'set.notifications')}</b>\n\n{t(lang, 'set.notify_hint', minutes=hub.settings.notification_poll_minutes)}",
               notifications_kb(lang, user))


@router.callback_query(Pref.filter(F.a == "nt"))
async def cb_toggle(cb: CallbackQuery, callback_data: Pref, hub: Hub, lang: str) -> None:
    kind = callback_data.v
    if kind not in ("tickets", "services", "payments"):
        return
    user = await hub.repo.get_or_create_user(cb.from_user.id)
    new_value = not user.wants(kind)
    user = await hub.repo.set_notification_pref(cb.from_user.id, kind, new_value)
    if new_value:  # re-seed so old changes are not replayed when re-enabled
        await hub.repo.reset_notification_state(cb.from_user.id, kind)
    await show(cb, f"🔔 <b>{t(lang, 'set.notifications')}</b>\n\n{t(lang, 'set.notify_hint', minutes=hub.settings.notification_poll_minutes)}",
               notifications_kb(lang, user))


@router.callback_query(Pref.filter(F.a == "api"))
async def cb_api(cb: CallbackQuery, hub: Hub, lang: str) -> None:
    await show_health(cb, hub, lang)


@router.callback_query(Pref.filter(F.a == "lim"))
async def cb_unavailable(cb: CallbackQuery, lang: str) -> None:
    await show(cb, t(lang, "help.unavailable"), back_to_settings_kb(lang))
