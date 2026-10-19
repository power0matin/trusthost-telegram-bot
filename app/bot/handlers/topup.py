from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import views
from app.bot.callbacks import Nav, Srv, Top
from app.bot.keyboards.billing import pay_options_kb
from app.bot.keyboards.common import btn, cancel_row, kb, nav_row
from app.bot.states import PromoStates
from app.bot.ui import Event, esc, fail, loading, show
from app.core.guard import OperationInProgress
from app.i18n import t
from app.services import validators
from app.services.container import Hub
from app.trusthost.exceptions import TrustHostError

router = Router(name="topup")


async def _promo_for(state: FSMContext, sid: int) -> str | None:
    data = await state.get_data()
    return data.get("topup_promo") if data.get("topup_service") == sid else None


async def render_quote(event: Event, state: FSMContext, hub: Hub, lang: str, sid: int) -> None:
    promo = await _promo_for(state, sid)
    try:
        svc = await hub.servers.service(sid)
        quote = await hub.traffic.topup_quote(sid, promo)
    except TrustHostError as exc:
        await fail(event, lang, exc, Srv(a="d", id=sid))
        return
    rows = [[btn(views.topup_option_label(lang, o), Top(a="s", id=sid, gb=o.gb))] for o in quote.options]
    if promo:
        rows.append([btn(t(lang, "btn.remove_promo"), Top(a="x", id=sid))])
    else:
        rows.append([btn(t(lang, "btn.enter_promo"), Top(a="p", id=sid))])
    rows.append(nav_row(lang, Srv(a="d", id=sid)))
    await show(event, views.topup_quote_text(lang, quote, svc, promo), kb(*rows))


@router.callback_query(Top.filter(F.a == "q"))
async def cb_quote(cb: CallbackQuery, callback_data: Top, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await state.update_data(topup_service=callback_data.id, topup_promo=None)
    await loading(cb, lang)
    await render_quote(cb, state, hub, lang, callback_data.id)


@router.callback_query(Top.filter(F.a == "x"))
async def cb_remove_promo(cb: CallbackQuery, callback_data: Top, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.update_data(topup_service=callback_data.id, topup_promo=None)
    await loading(cb, lang)
    await render_quote(cb, state, hub, lang, callback_data.id)


@router.callback_query(Top.filter(F.a == "p"))
async def cb_promo_prompt(cb: CallbackQuery, callback_data: Top, state: FSMContext, lang: str) -> None:
    await state.set_state(PromoStates.topup)
    await state.update_data(topup_service=callback_data.id)
    await show(cb, t(lang, "promo.prompt_topup"), kb(cancel_row(lang, Top(a="x", id=callback_data.id))))


@router.message(StateFilter(PromoStates.topup), F.text, ~F.text.startswith("/"))
async def msg_promo(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    data = await state.get_data()
    sid = int(data.get("topup_service", 0))
    try:
        code = validators.promo_code(message.text or "")
    except validators.InputError as exc:
        await message.answer(t(lang, exc.key), reply_markup=kb(cancel_row(lang, Top(a="x", id=sid))))
        return
    await state.set_state(None)
    await state.update_data(topup_promo=code, topup_service=sid)
    await render_quote(message, state, hub, lang, sid)


@router.callback_query(Top.filter(F.a == "s"))
async def cb_select(cb: CallbackQuery, callback_data: Top, state: FSMContext, hub: Hub, lang: str) -> None:
    sid, gb = callback_data.id, callback_data.gb
    promo = await _promo_for(state, sid)
    await loading(cb, lang)
    try:
        svc = await hub.servers.service(sid)
        quote = await hub.traffic.topup_quote(sid, promo)  # re-check: tiers are API-defined and may change
    except TrustHostError as exc:
        await fail(cb, lang, exc, Top(a="q", id=sid))
        return
    opt = next((o for o in quote.options if o.gb == gb), None)
    if opt is None:
        from app.trusthost.exceptions import TrustHostBadRequestError
        await fail(cb, lang, TrustHostBadRequestError("TRAFFIC_TIER_UNAVAILABLE", status=400), Top(a="q", id=sid))
        return
    applied = promo if (quote.promo and quote.promo.valid) else None
    markup = kb([btn(t(lang, "btn.confirm_topup"), Top(a="go", id=sid, gb=gb)), btn(t(lang, "btn.cancel"), Top(a="q", id=sid))],
                nav_row(lang, Top(a="q", id=sid)))
    await show(cb, views.topup_confirm_text(lang, gb, opt, applied, svc), markup)


@router.callback_query(Top.filter(F.a == "go"))
async def cb_create(cb: CallbackQuery, callback_data: Top, state: FSMContext, hub: Hub, lang: str) -> None:
    sid, gb = callback_data.id, callback_data.gb
    promo = await _promo_for(state, sid)
    try:
        await loading(cb, lang, "processing")
        result = await hub.traffic.topup_create(cb.from_user.id, sid, gb, promo)
    except OperationInProgress:
        return
    except validators.InputError:
        await fail(cb, lang, TrustHostError(), Top(a="q", id=sid))
        return
    except TrustHostError as exc:
        await fail(cb, lang, exc, Top(a="s", id=sid, gb=gb), hub=hub)
        return
    await state.update_data(topup_promo=None)
    text = views.topup_result_text(lang, result)
    if (result.status or "").lower() == "paid" or not result.invoice_id:
        await show(cb, text, kb(nav_row(lang, Srv(a="tr", id=sid))))
    else:
        await show(cb, text, pay_options_kb(lang, result.invoice_id, None, Srv(a="d", id=sid)))
