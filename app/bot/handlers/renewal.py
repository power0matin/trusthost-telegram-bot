from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import views
from app.bot.callbacks import Ren, Srv
from app.bot.keyboards.billing import pay_options_kb
from app.bot.keyboards.common import btn, cancel_row, kb, nav_row
from app.bot.states import PromoStates
from app.bot.ui import fail, loading, show
from app.core.guard import OperationInProgress
from app.i18n import t
from app.services import validators
from app.services.container import Hub
from app.trusthost.exceptions import TrustHostError

router = Router(name="renewal")


@router.callback_query(Ren.filter(F.a == "s"))
async def cb_start(cb: CallbackQuery, callback_data: Ren, state: FSMContext, hub: Hub, lang: str) -> None:
    sid = callback_data.id
    await state.clear()
    try:
        svc = await hub.servers.service(sid)
    except TrustHostError as exc:
        await fail(cb, lang, exc, Srv(a="l"))
        return
    markup = kb([btn(t(lang, "btn.enter_promo"), Ren(a="p", id=sid))],
                [btn(t(lang, "btn.issue_invoice"), Ren(a="c", id=sid))],
                nav_row(lang, Srv(a="d", id=sid)))
    await show(cb, views.renew_start_text(lang, svc), markup)


@router.callback_query(Ren.filter(F.a == "p"))
async def cb_promo(cb: CallbackQuery, callback_data: Ren, state: FSMContext, lang: str) -> None:
    await state.set_state(PromoStates.renew)
    await state.update_data(renew_service=callback_data.id, renew_promo=None)
    await show(cb, t(lang, "promo.prompt_renew"), kb(cancel_row(lang, Ren(a="s", id=callback_data.id))))


async def _confirm(event: CallbackQuery | Message, state: FSMContext, hub: Hub, lang: str, sid: int, promo: str | None) -> None:
    try:
        svc = await hub.servers.service(sid)
    except TrustHostError as exc:
        await fail(event, lang, exc, Srv(a="l"))
        return
    await state.set_state(None)
    await state.update_data(renew_service=sid, renew_promo=promo)
    markup = kb([btn(t(lang, "btn.confirm_renew"), Ren(a="go", id=sid)), btn(t(lang, "btn.cancel"), Ren(a="s", id=sid))],
                nav_row(lang, Srv(a="d", id=sid)))
    await show(event, views.renew_confirm_text(lang, svc, promo), markup)


@router.message(StateFilter(PromoStates.renew), F.text, ~F.text.startswith("/"))
async def msg_promo(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    sid = int((await state.get_data()).get("renew_service", 0))
    try:
        code = validators.promo_code(message.text or "")
    except validators.InputError as exc:
        await message.answer(t(lang, exc.key), reply_markup=kb(cancel_row(lang, Ren(a="s", id=sid))))
        return
    await _confirm(message, state, hub, lang, sid, code)


@router.callback_query(Ren.filter(F.a == "c"))
async def cb_confirm_no_promo(cb: CallbackQuery, callback_data: Ren, state: FSMContext, hub: Hub, lang: str) -> None:
    await _confirm(cb, state, hub, lang, callback_data.id, None)


@router.callback_query(Ren.filter(F.a == "go"))
async def cb_go(cb: CallbackQuery, callback_data: Ren, state: FSMContext, hub: Hub, lang: str) -> None:
    sid = callback_data.id
    data = await state.get_data()
    promo = data.get("renew_promo") if data.get("renew_service") == sid else None
    try:
        await loading(cb, lang, "processing")
        result = await hub.servers.renew(cb.from_user.id, sid, promo)  # returns existing unpaid invoice → no duplicates
    except OperationInProgress:
        return
    except TrustHostError as exc:
        await fail(cb, lang, exc, Ren(a="s", id=sid), hub=hub)
        return
    await state.update_data(renew_promo=None)
    text = views.renew_result_text(lang, result)
    if result.invoice_id:
        await show(cb, text, pay_options_kb(lang, result.invoice_id, None, Srv(a="d", id=sid)))
    else:
        await show(cb, text, kb(nav_row(lang, Srv(a="d", id=sid))))
