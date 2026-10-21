from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.callbacks import NewT, Tkt
from app.bot.keyboards.common import Row, btn, cancel_row, kb, nav_row, paginate, pager_row
from app.core.constants import LIST_PAGE_SIZE, PAGE_SIZE, PRIORITY_CODES
from app.i18n import t
from app.trusthost.models import Department, Service, Ticket


def support_menu_kb(lang: str) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "tkt.my"), Tkt(a="l")), btn(t(lang, "tkt.new"), NewT(a="s"))], nav_row(lang))


def tickets_list_kb(lang: str, tickets: list[Ticket], page: int) -> tuple[InlineKeyboardMarkup, list[Ticket], int, int]:
    items, page, pages = paginate(tickets, page, LIST_PAGE_SIZE)
    rows: list[Row | None] = [[btn(f"🎫 #{tk.tid} · {tk.subject}"[:60], Tkt(a="d", id=tk.id, p=page))] for tk in items]
    rows.append(pager_row(page, pages, lambda p: Tkt(a="l", p=p)))
    rows.append([btn(t(lang, "btn.refresh"), Tkt(a="l", p=page, id=1)), btn(t(lang, "tkt.new"), NewT(a="s"))])
    rows.append(nav_row(lang, Tkt(a="m")))
    return kb(*rows), items, page, pages


def ticket_detail_kb(lang: str, ticket_id: int, page: int, *, closed: bool = False) -> InlineKeyboardMarkup:
    rows: list[Row | None] = [[btn(t(lang, "btn.reply"), Tkt(a="r", id=ticket_id, p=page)),
                               btn(t(lang, "btn.refresh"), Tkt(a="d", id=ticket_id, p=page))]]
    if not closed:
        rows.append([btn(t(lang, "btn.close_ticket"), Tkt(a="cx", id=ticket_id, p=page))])
    rows.append(nav_row(lang, Tkt(a="l", p=page)))
    return kb(*rows)


def ticket_close_kb(lang: str, ticket_id: int, page: int) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "btn.confirm_close"), Tkt(a="cc", id=ticket_id, p=page)),
               btn(t(lang, "btn.no_cancel"), Tkt(a="d", id=ticket_id, p=page))])


def departments_kb(lang: str, depts: list[Department]) -> InlineKeyboardMarkup:
    rows: list[Row | None] = [[btn(f"🏢 {d.name}"[:60], NewT(a="d", v=d.id))] for d in depts]
    rows.append(cancel_row(lang, Tkt(a="m")))
    return kb(*rows)


def priority_kb(lang: str) -> InlineKeyboardMarkup:
    icons = {"L": "🟢", "M": "🟡", "H": "🔴"}
    return kb([btn(f"{icons[c]} {t(lang, f'prio.{p.lower()}')}", NewT(a="pr", s=c)) for c, p in PRIORITY_CODES.items()],
              cancel_row(lang))


def service_pick_kb(lang: str, services: list[Service], page: int) -> InlineKeyboardMarkup:
    items, page, pages = paginate(services, page, PAGE_SIZE)
    rows: list[Row | None] = [[btn(t(lang, "tkt.no_service_btn"), NewT(a="sv", v=0))]]
    rows += [[btn(f"🖥 {s.product_name} · #{s.id}"[:60], NewT(a="sv", v=s.id))] for s in items]
    rows.append(pager_row(page, pages, lambda p: NewT(a="svl", p=p)))
    rows.append(cancel_row(lang))
    return kb(*rows)


def ticket_review_kb(lang: str) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "btn.submit"), NewT(a="go")), btn(t(lang, "btn.cancel"), NewT(a="x"))])


def prompt_kb(lang: str, back: object | None = None) -> InlineKeyboardMarkup:
    return kb(cancel_row(lang, back))  # type: ignore[arg-type]
