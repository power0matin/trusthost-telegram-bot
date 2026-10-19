from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot import views
from app.bot.callbacks import Inv
from app.bot.keyboards.billing import (
    invoice_detail_kb, invoices_list_kb, invoices_menu_kb, pay_confirm_kb, pay_done_kb, url_screen_kb, wallet_kb,
)
from app.bot.ui import Event, fail, loading, show
from app.core.constants import INVOICE_FILTERS
from app.core.guard import OperationInProgress
from app.i18n import t
from app.services.container import Hub
from app.trusthost.exceptions import TrustHostError

router = Router(name="billing")

_FILTER_KEYS = {"u": "unpaid", "p": "paid", "c": "cancelled", "r": "refunded", "a": "all"}


async def show_invoices_menu(event: Event, lang: str) -> None:
    await show(event, f"💳 <b>{t(lang, 'inv.title')}</b>\n\n{t(lang, 'inv.pick_filter')}\n\n{t(lang, 'inv.limit_note')}",
               invoices_menu_kb(lang))


async def show_wallet(event: Event, hub: Hub, lang: str) -> None:
    await loading(event, lang)
    try:
        wallet = await hub.billing.wallet(force=True)
    except TrustHostError as exc:
        await fail(event, lang, exc, None)
        return
    await show(event, views.wallet_text(lang, wallet.balance), wallet_kb(lang, wallet.add_funds_url))


@router.callback_query(Inv.filter(F.a == "m"))
async def cb_menu(cb: CallbackQuery, lang: str) -> None:
    await show_invoices_menu(cb, lang)


@router.callback_query(Inv.filter(F.a == "l"))
async def cb_list(cb: CallbackQuery, callback_data: Inv, hub: Hub, lang: str) -> None:
    flt = callback_data.f if callback_data.f in INVOICE_FILTERS else "a"
    await loading(cb, lang)
    try:
        invoices = await hub.billing.invoices(INVOICE_FILTERS[flt], force=bool(callback_data.id))
    except TrustHostError as exc:
        await fail(cb, lang, exc, Inv(a="m"))
        return
    markup, items, page, pages = invoices_list_kb(lang, invoices, callback_data.p, flt)
    await show(cb, views.invoices_list_text(lang, items, page, pages, len(invoices), _FILTER_KEYS[flt]), markup)


@router.callback_query(Inv.filter(F.a == "d"))
async def cb_detail(cb: CallbackQuery, callback_data: Inv, hub: Hub, lang: str) -> None:
    await loading(cb, lang)
    try:
        inv = await hub.billing.invoice(callback_data.id)  # always fresh: status may have just changed
    except TrustHostError as exc:
        await fail(cb, lang, exc, Inv(a="l", f=callback_data.f, p=callback_data.p))
        return
    await show(cb, views.invoice_card(lang, inv, detailed=True), invoice_detail_kb(lang, inv, callback_data.f, callback_data.p))


@router.callback_query(Inv.filter(F.a == "pc"))
async def cb_pay_preview(cb: CallbackQuery, callback_data: Inv, hub: Hub, lang: str) -> None:
    await loading(cb, lang)
    back = Inv(a="d", id=callback_data.id, f=callback_data.f, p=callback_data.p)
    try:
        preview = await hub.billing.pay_preview(callback_data.id)
    except TrustHostError as exc:
        await fail(cb, lang, exc, back)
        return
    can_pay = preview.unpaid and preview.sufficient
    await show(cb, views.pay_preview_text(lang, preview),
               pay_confirm_kb(lang, callback_data.id, callback_data.f, callback_data.p, can_pay=can_pay,
                              add_funds_url=preview.add_funds_url))


@router.callback_query(Inv.filter(F.a == "pd"))
async def cb_pay_do(cb: CallbackQuery, callback_data: Inv, hub: Hub, lang: str) -> None:
    back = Inv(a="d", id=callback_data.id, f=callback_data.f, p=callback_data.p)
    try:
        await loading(cb, lang, "processing")
        # Re-check the live state right before spending money.
        preview = await hub.billing.pay_preview(callback_data.id)
        if not preview.unpaid or not preview.sufficient:
            await show(cb, views.pay_preview_text(lang, preview),
                       pay_confirm_kb(lang, callback_data.id, callback_data.f, callback_data.p, can_pay=False,
                                      add_funds_url=preview.add_funds_url))
            return
        result = await hub.billing.pay_with_wallet(cb.from_user.id, callback_data.id)
    except OperationInProgress:
        return
    except TrustHostError as exc:
        await fail(cb, lang, exc, back, hub=hub)
        return
    await show(cb, views.pay_success_text(lang, result), pay_done_kb(lang))


async def _url_screen(cb: CallbackQuery, callback_data: Inv, hub: Hub, lang: str, gateway: str | None) -> None:
    await loading(cb, lang)
    back = Inv(a="d", id=callback_data.id, f=callback_data.f, p=callback_data.p)
    try:
        link = await hub.billing.pay_url(callback_data.id, gateway)
    except TrustHostError as exc:  # ALREADY_PAID arrives as success:false
        await fail(cb, lang, exc, back)
        return
    await show(cb, views.pay_url_text(lang, gateway == "usdt", link.amount),
               url_screen_kb(lang, link.direct_payment_url, callback_data.id, callback_data.f, callback_data.p))


@router.callback_query(Inv.filter(F.a == "po"))
async def cb_online(cb: CallbackQuery, callback_data: Inv, hub: Hub, lang: str) -> None:
    await _url_screen(cb, callback_data, hub, lang, None)


@router.callback_query(Inv.filter(F.a == "pu"))
async def cb_usdt(cb: CallbackQuery, callback_data: Inv, hub: Hub, lang: str) -> None:
    await _url_screen(cb, callback_data, hub, lang, "usdt")
