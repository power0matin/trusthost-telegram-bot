from __future__ import annotations

from typing import Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import Lang, Menu, Nav
from app.i18n import t

Row = list[InlineKeyboardButton]


def btn(text: str, cb: CallbackData | str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb if isinstance(cb, str) else cb.pack())


def safe_url(url: str | None) -> str | None:
    """Telegram URL buttons must be http(s)."""
    if url and url.lower().startswith(("https://", "http://")):
        return url
    return None


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def kb(*rows: Row | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def nav_row(lang: str, back: CallbackData | None = None) -> Row:
    row: Row = []
    if back is not None:
        row.append(btn(t(lang, "btn.back"), back))
    row.append(btn(t(lang, "btn.home"), Nav(a="home")))
    return row


def cancel_row(lang: str, back: CallbackData | None = None) -> Row:
    row: Row = []
    if back is not None:
        row.append(btn(t(lang, "btn.back"), back))
    row.append(btn(t(lang, "btn.cancel"), Nav(a="cancel")))
    return row


def error_keyboard(lang: str, back: CallbackData | None, add_funds_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[Row] = []
    url = safe_url(add_funds_url)
    if url:
        rows.append([url_btn(t(lang, "btn.add_funds"), url)])
    rows.append(nav_row(lang, back))
    return kb(*rows)


def paginate(items: list[Any], page: int, size: int) -> tuple[list[Any], int, int]:
    pages = max(1, -(-len(items) // size))
    page = max(0, min(page, pages - 1))
    return items[page * size:(page + 1) * size], page, pages


def pager_row(page: int, pages: int, make: Any) -> Row | None:
    """`make(page) -> CallbackData`. Returns ◀️ n/m ▶️ or None for a single page."""
    if pages <= 1:
        return None
    row: Row = []
    row.append(btn("◀️", make(page - 1)) if page > 0 else btn("·", Nav(a="noop")))
    row.append(btn(f"{page + 1}/{pages}", Nav(a="noop")))
    row.append(btn("▶️", make(page + 1)) if page < pages - 1 else btn("·", Nav(a="noop")))
    return row


def main_menu(lang: str) -> InlineKeyboardMarkup:
    def b(k: str, a: str) -> InlineKeyboardButton:
        return btn(t(lang, f"menu.{k}"), Menu(a=a))
    return kb(
        [b("servers", "srv"), b("order", "order")],
        [b("invoices", "inv"), b("wallet", "wal")],
        [b("usage", "usage"), b("support", "support")],
        [b("settings", "settings"), btn(t(lang, "btn.refresh"), Menu(a="refresh"))],
    )


def language_keyboard(src: str = "s") -> InlineKeyboardMarkup:
    return kb([btn("🇮🇷 فارسی", Lang(code="fa", src=src)), btn("🇬🇧 English", Lang(code="en", src=src))])
