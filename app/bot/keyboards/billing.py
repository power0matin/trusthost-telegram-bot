from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup

from app.bot.callbacks import Inv, Menu, Srv, Wal
from app.bot.keyboards.common import Row, btn, kb, nav_row, paginate, pager_row, safe_url, url_btn
from app.core.constants import LIST_PAGE_SIZE
from app.i18n import t
from app.trusthost.models import Invoice


def pay_options_kb(lang: str, invoice_id: int, online_url: str | None, back: CallbackData | None,
                   *, flt: str = "a", page: int = 0) -> InlineKeyboardMarkup:
    """Payment choices for an unpaid invoice: wallet · online (URL button when known) · USDT."""
    url = safe_url(online_url)
    online = url_btn(t(lang, "btn.pay_online"), url) if url else btn(t(lang, "btn.pay_online"), Inv(a="po", id=invoice_id, f=flt, p=page))
    return kb(
        [btn(t(lang, "btn.pay_wallet"), Inv(a="pc", id=invoice_id, f=flt, p=page))],
        [online],
        [btn(t(lang, "btn.pay_usdt"), Inv(a="pu", id=invoice_id, f=flt, p=page))],
        [btn(t(lang, "btn.check_status"), Inv(a="d", id=invoice_id, f=flt, p=page))],
        nav_row(lang, back),
    )


def invoices_menu_kb(lang: str) -> InlineKeyboardMarkup:
    b = lambda key, f: btn(t(lang, f"inv.filter_{key}"), Inv(a="l", f=f))  # noqa: E731
    return kb([b("unpaid", "u"), b("paid", "p")], [b("cancelled", "c"), b("refunded", "r")], [b("all", "a")],
              nav_row(lang))


def invoices_list_kb(lang: str, invoices: list[Invoice], page: int, flt: str) -> tuple[InlineKeyboardMarkup, list[Invoice], int, int]:
    items, page, pages = paginate(invoices, page, LIST_PAGE_SIZE)
    rows: list[Row | None] = [[btn(f"📄 #{i.invoicenum or i.id} · {i.status}", Inv(a="d", id=i.id, f=flt, p=page))]
                              for i in items]
    rows.append(pager_row(page, pages, lambda p: Inv(a="l", f=flt, p=p)))
    rows.append([btn(t(lang, "btn.refresh"), Inv(a="l", f=flt, p=page, id=1))])
    rows.append(nav_row(lang, Inv(a="m")))
    return kb(*rows), items, page, pages


def invoice_detail_kb(lang: str, inv: Invoice, flt: str, page: int) -> InlineKeyboardMarkup:
    back = Inv(a="l", f=flt, p=page)
    if inv.is_unpaid:
        return pay_options_kb(lang, inv.id, inv.best_url, back, flt=flt, page=page)
    return kb([btn(t(lang, "btn.refresh"), Inv(a="d", id=inv.id, f=flt, p=page))], nav_row(lang, back))


def pay_confirm_kb(lang: str, invoice_id: int, flt: str, page: int, *, can_pay: bool,
                   add_funds_url: str | None) -> InlineKeyboardMarkup:
    rows: list[Row | None] = []
    if can_pay:
        rows.append([btn(t(lang, "btn.confirm_pay"), Inv(a="pd", id=invoice_id, f=flt, p=page)),
                     btn(t(lang, "btn.no_cancel"), Inv(a="d", id=invoice_id, f=flt, p=page))])
    else:
        url = safe_url(add_funds_url)
        if url:
            rows.append([url_btn(t(lang, "btn.add_funds"), url)])
        rows.append([btn(t(lang, "btn.pay_usdt"), Inv(a="pu", id=invoice_id, f=flt, p=page))])
    rows.append(nav_row(lang, Inv(a="d", id=invoice_id, f=flt, p=page)))
    return kb(*rows)


def pay_done_kb(lang: str) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "menu.invoices"), Menu(a="inv")), btn(t(lang, "menu.servers"), Srv(a="l"))], nav_row(lang))


def url_screen_kb(lang: str, url: str | None, invoice_id: int, flt: str, page: int) -> InlineKeyboardMarkup:
    rows: list[Row | None] = []
    safe = safe_url(url)
    if safe:
        rows.append([url_btn(t(lang, "btn.open_payment"), safe)])
    rows.append([btn(t(lang, "btn.check_status"), Inv(a="d", id=invoice_id, f=flt, p=page))])
    rows.append(nav_row(lang, Inv(a="d", id=invoice_id, f=flt, p=page)))
    return kb(*rows)


def wallet_kb(lang: str, add_funds_url: str | None) -> InlineKeyboardMarkup:
    rows: list[Row | None] = []
    url = safe_url(add_funds_url)
    if url:
        rows.append([url_btn(t(lang, "btn.add_funds"), url)])
    rows.append([btn(t(lang, "btn.wallet_topup"), Wal(a="t"))])
    rows.append([btn(t(lang, "inv.filter_unpaid"), Inv(a="l", f="u")), btn(t(lang, "btn.refresh"), Menu(a="wal"))])
    rows.append(nav_row(lang))
    return kb(*rows)


def topup_gateway_kb(lang: str) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "btn.pay_card"), Wal(a="go")), btn(t(lang, "btn.pay_usdt"), Wal(a="go", g="u"))],
              [btn(t(lang, "btn.cancel"), Menu(a="wal"))])


def topup_created_kb(lang: str, url: str | None, invoice_id: int | None) -> InlineKeyboardMarkup:
    rows: list[Row | None] = []
    safe = safe_url(url)
    if safe:
        rows.append([url_btn(t(lang, "btn.open_payment"), safe)])
    if invoice_id:
        rows.append([btn(t(lang, "btn.check_status"), Inv(a="d", id=invoice_id))])
    rows.append(nav_row(lang, Menu(a="wal")))
    return kb(*rows)
