from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.callbacks import Pref
from app.bot.keyboards.common import btn, kb, nav_row
from app.database.repository import UserRecord
from app.i18n import t


def settings_kb(lang: str) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "set.language"), Pref(a="lang"))],
              [btn(t(lang, "set.notifications"), Pref(a="notif"))],
              [btn(t(lang, "set.api_status"), Pref(a="api"))],
              [btn(t(lang, "set.unavailable"), Pref(a="lim"))],
              nav_row(lang))


def notifications_kb(lang: str, user: UserRecord) -> InlineKeyboardMarkup:
    def row(kind: str) -> list:
        on = user.wants(kind)
        return [btn(f"{'✅' if on else '❌'} {t(lang, f'set.notify_{kind}')}", Pref(a="nt", v=kind))]
    return kb(row("tickets"), row("services"), row("payments"), nav_row(lang, Pref(a="menu")))


def back_to_settings_kb(lang: str) -> InlineKeyboardMarkup:
    return kb(nav_row(lang, Pref(a="menu")))


def health_kb(lang: str) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "btn.refresh"), Pref(a="api"))], nav_row(lang, Pref(a="menu")))
