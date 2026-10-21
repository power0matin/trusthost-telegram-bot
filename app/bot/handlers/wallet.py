from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import views
from app.bot.callbacks import Menu, Wal
from app.bot.keyboards.billing import topup_created_kb, topup_gateway_kb
from app.bot.keyboards.common import cancel_row, kb
from app.bot.states import WalletStates
from app.bot.ui import fail, loading, show
from app.core.constants import MIN_TOPUP_AMOUNT
from app.core.formatting import Fmt
from app.core.guard import OperationInProgress
from app.i18n import t
from app.services import validators
from app.services.container import Hub
from app.trusthost.exceptions import TrustHostError

router = Router(name="wallet")


@router.callback_query(Wal.filter(F.a == "t"))
async def cb_topup_start(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.clear()
    await state.set_state(WalletStates.amount)
    await show(cb, t(lang, "wtop.prompt", min=Fmt(lang).money(MIN_TOPUP_AMOUNT)), kb(cancel_row(lang, Menu(a="wal"))))


@router.message(StateFilter(WalletStates.amount), F.text, ~F.text.startswith("/"))
async def msg_amount(message: Message, state: FSMContext, lang: str) -> None:
    try:
        amount = validators.wallet_amount(message.text or "")
    except validators.InputError as exc:
        await message.answer(t(lang, exc.key, min=Fmt(lang).money(exc.ctx.get("min", MIN_TOPUP_AMOUNT))),
                             reply_markup=kb(cancel_row(lang, Menu(a="wal"))))
        return
    await state.set_state(None)
    await state.update_data(wallet_topup_amount=amount)
    await message.answer(views.wallet_topup_confirm_text(lang, amount), reply_markup=topup_gateway_kb(lang))


@router.callback_query(Wal.filter(F.a == "go"))
async def cb_topup_go(cb: CallbackQuery, callback_data: Wal, state: FSMContext, hub: Hub, lang: str) -> None:
    amount = (await state.get_data()).get("wallet_topup_amount")
    if not isinstance(amount, int):
        await show(cb, t(lang, "wtop.expired"), kb(cancel_row(lang, Menu(a="wal"))))
        return
    gateway = "usdt" if callback_data.g == "u" else None
    try:
        await loading(cb, lang, "processing")
        await state.update_data(wallet_topup_amount=None)  # one confirmation = one invoice
        result = await hub.billing.topup(cb.from_user.id, amount, gateway)
    except OperationInProgress:
        return
    except validators.InputError as exc:
        await show(cb, t(lang, exc.key, min=Fmt(lang).money(exc.ctx.get("min", MIN_TOPUP_AMOUNT))),
                   kb(cancel_row(lang, Menu(a="wal"))))
        return
    except TrustHostError as exc:
        await fail(cb, lang, exc, Menu(a="wal"), hub=hub)
        return
    await show(cb, views.wallet_topup_created_text(lang, result),
               topup_created_kb(lang, result.best_url, result.invoice_id))
