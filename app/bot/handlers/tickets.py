from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import views
from app.bot.callbacks import NewT, Tkt
from app.bot.keyboards import tickets as kbt
from app.bot.keyboards.common import btn, kb, nav_row
from app.bot.states import TicketStates
from app.bot.ui import Event, esc, fail, loading, show
from app.core.constants import PRIORITY_CODES
from app.core.guard import OperationInProgress
from app.i18n import t
from app.services import validators
from app.services.container import Hub
from app.trusthost.exceptions import TrustHostError

router = Router(name="tickets")


async def show_support_menu(event: Event, lang: str) -> None:
    await show(event, f"🎫 <b>{t(lang, 'support.title')}</b>\n\n{t(lang, 'support.hint')}", kbt.support_menu_kb(lang))


@router.callback_query(Tkt.filter(F.a == "m"))
async def cb_menu(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.clear()
    await show_support_menu(cb, lang)


@router.callback_query(Tkt.filter(F.a == "l"))
async def cb_list(cb: CallbackQuery, callback_data: Tkt, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await loading(cb, lang)
    try:
        tickets = await hub.tickets.tickets(force=bool(callback_data.id))
    except TrustHostError as exc:
        await fail(cb, lang, exc, Tkt(a="m"))
        return
    markup, items, page, pages = kbt.tickets_list_kb(lang, tickets, callback_data.p)
    await show(cb, views.tickets_list_text(lang, items, page, pages, len(tickets)), markup)


async def render_detail(event: Event, hub: Hub, lang: str, ticket_id: int, page: int = 0, *, new: bool = False) -> None:
    try:
        detail = await hub.tickets.detail(ticket_id)
        priority = next((tk.priority for tk in await hub.tickets.tickets() if tk.id == ticket_id), None)
    except TrustHostError as exc:
        await fail(event, lang, exc, Tkt(a="l", p=page))
        return
    await show(event, views.ticket_detail_text(lang, detail, priority), kbt.ticket_detail_kb(lang, ticket_id, page), new=new)


@router.callback_query(Tkt.filter(F.a == "d"))
async def cb_detail(cb: CallbackQuery, callback_data: Tkt, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await loading(cb, lang)
    await render_detail(cb, hub, lang, callback_data.id, callback_data.p)


@router.callback_query(Tkt.filter(F.a == "r"))
async def cb_reply_prompt(cb: CallbackQuery, callback_data: Tkt, state: FSMContext, lang: str) -> None:
    await state.set_state(TicketStates.reply)
    await state.update_data(reply_ticket=callback_data.id, reply_page=callback_data.p)
    await show(cb, t(lang, "tkt.prompt_reply"), kb([btn(t(lang, "btn.cancel"), Tkt(a="d", id=callback_data.id, p=callback_data.p))]))


@router.message(StateFilter(TicketStates.reply), F.text, ~F.text.startswith("/"))
async def msg_reply(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    data = await state.get_data()
    tid, page = int(data.get("reply_ticket", 0)), int(data.get("reply_page", 0))
    try:
        await hub.tickets.reply(message.from_user.id, tid, message.text or "")
    except validators.InputError as exc:
        await message.answer(t(lang, exc.key, max=exc.ctx.get("max", "")))
        return
    except OperationInProgress:
        return
    except TrustHostError as exc:
        await fail(message, lang, exc, Tkt(a="d", id=tid, p=page))
        return
    await state.clear()
    await message.answer(t(lang, "tkt.reply_sent"))
    await render_detail(message, hub, lang, tid, page, new=True)


# ------------------------------------------------------------------ new ticket
async def _nt(state: FSMContext) -> dict:
    return dict((await state.get_data()).get("nt") or {})


async def _set_nt(state: FSMContext, nt: dict) -> None:
    await state.update_data(nt=nt)


@router.callback_query(NewT.filter(F.a == "s"))
async def cb_new(cb: CallbackQuery, callback_data: NewT, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await loading(cb, lang)
    nt: dict = {"service_id": callback_data.v or None}
    try:
        if nt["service_id"]:
            svc = await hub.servers.service(nt["service_id"])
            nt["service_label"] = f"{svc.product_name} · #{svc.id}"
        depts = await hub.tickets.departments()
    except TrustHostError as exc:
        await fail(cb, lang, exc, Tkt(a="m"))
        return
    await _set_nt(state, nt)
    lines = [f"🎫 <b>{t(lang, 'tkt.new')}</b>", "", t(lang, "tkt.pick_dept")]
    for d in depts:
        if d.description:
            lines.append(f"• <b>{esc(d.name)}</b> — {esc(d.description[:80])}")
    await show(cb, "\n".join(lines), kbt.departments_kb(lang, depts))


@router.callback_query(NewT.filter(F.a == "d"))
async def cb_dept(cb: CallbackQuery, callback_data: NewT, state: FSMContext, hub: Hub, lang: str) -> None:
    nt = await _nt(state)
    try:
        depts = await hub.tickets.departments()
    except TrustHostError as exc:
        await fail(cb, lang, exc, Tkt(a="m"))
        return
    dept = next((d for d in depts if d.id == callback_data.v), None)
    if dept is None:
        await show(cb, t(lang, "order.expired"), kb(nav_row(lang)))
        return
    nt.update(dept_id=dept.id, dept_name=dept.name)
    await _set_nt(state, nt)
    await state.set_state(TicketStates.subject)
    await show(cb, t(lang, "tkt.prompt_subject"), kbt.prompt_kb(lang))


@router.message(StateFilter(TicketStates.subject), F.text, ~F.text.startswith("/"))
async def msg_subject(message: Message, state: FSMContext, lang: str) -> None:
    try:
        subject = validators.ticket_subject(message.text or "")
    except validators.InputError as exc:
        await message.answer(t(lang, exc.key, max=exc.ctx.get("max", "")), reply_markup=kbt.prompt_kb(lang))
        return
    nt = await _nt(state)
    nt["subject"] = subject
    await _set_nt(state, nt)
    await state.set_state(TicketStates.message)
    await message.answer(t(lang, "tkt.prompt_message"), reply_markup=kbt.prompt_kb(lang))


@router.message(StateFilter(TicketStates.message), F.text, ~F.text.startswith("/"))
async def msg_message(message: Message, state: FSMContext, lang: str) -> None:
    try:
        text = validators.ticket_message(message.text or "")
    except validators.InputError as exc:
        await message.answer(t(lang, exc.key, max=exc.ctx.get("max", "")), reply_markup=kbt.prompt_kb(lang))
        return
    nt = await _nt(state)
    nt["message"] = text
    await _set_nt(state, nt)
    await state.set_state(None)
    await message.answer(t(lang, "tkt.pick_priority"), reply_markup=kbt.priority_kb(lang))


async def _review(event: Event, state: FSMContext, lang: str, *, new: bool = False) -> None:
    nt = await _nt(state)
    await show(event, views.new_ticket_review(lang, nt.get("dept_name", ""), nt.get("subject", ""), nt.get("message", ""),
                                              nt.get("priority", "Medium"), nt.get("service_label")),
               kbt.ticket_review_kb(lang), new=new)


@router.callback_query(NewT.filter(F.a == "pr"))
async def cb_priority(cb: CallbackQuery, callback_data: NewT, state: FSMContext, hub: Hub, lang: str) -> None:
    priority = PRIORITY_CODES.get(callback_data.s)
    nt = await _nt(state)
    if priority is None or "message" not in nt:
        await show(cb, t(lang, "order.expired"), kb(nav_row(lang)))
        return
    nt["priority"] = priority
    await _set_nt(state, nt)
    if nt.get("service_id"):  # opened from a server screen: service already chosen
        await _review(cb, state, lang)
        return
    await _service_pick(cb, state, hub, lang, 0)


async def _service_pick(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str, page: int) -> None:
    try:
        services = await hub.servers.services()
    except TrustHostError as exc:
        await fail(cb, lang, exc, Tkt(a="m"))
        return
    if not services:
        await _review(cb, state, lang)
        return
    await show(cb, t(lang, "tkt.pick_service"), kbt.service_pick_kb(lang, services, page))


@router.callback_query(NewT.filter(F.a == "svl"))
async def cb_service_page(cb: CallbackQuery, callback_data: NewT, state: FSMContext, hub: Hub, lang: str) -> None:
    await _service_pick(cb, state, hub, lang, callback_data.p)


@router.callback_query(NewT.filter(F.a == "sv"))
async def cb_service(cb: CallbackQuery, callback_data: NewT, state: FSMContext, hub: Hub, lang: str) -> None:
    nt = await _nt(state)
    if callback_data.v:
        try:
            svc = await hub.servers.service(callback_data.v)  # must belong to this account
        except TrustHostError as exc:
            await fail(cb, lang, exc, Tkt(a="m"))
            return
        nt.update(service_id=svc.id, service_label=f"{svc.product_name} · #{svc.id}")
    else:
        nt.pop("service_id", None)
        nt.pop("service_label", None)
    await _set_nt(state, nt)
    await _review(cb, state, lang)


@router.callback_query(NewT.filter(F.a == "x"))
async def cb_cancel(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.clear()
    await show_support_menu(cb, lang)


@router.callback_query(NewT.filter(F.a == "go"))
async def cb_submit(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    nt = await _nt(state)
    if not {"dept_id", "subject", "message"} <= set(nt):
        await show(cb, t(lang, "order.expired"), kb(nav_row(lang)))
        return
    try:
        await loading(cb, lang, "processing")
        result = await hub.tickets.create(cb.from_user.id, dept_id=nt["dept_id"], subject=nt["subject"],
                                          message=nt["message"], priority=nt.get("priority", "Medium"),
                                          service_id=nt.get("service_id"))
    except OperationInProgress:
        return
    except TrustHostError as exc:
        await fail(cb, lang, exc, Tkt(a="m"))
        return
    except validators.InputError as exc:
        await show(cb, t(lang, exc.key, max=exc.ctx.get("max", "")), kb(nav_row(lang, Tkt(a="m"))))
        return
    await state.clear()
    await show(cb, t(lang, "tkt.created", tid=esc(result.tid)),
               kb([btn(t(lang, "btn.view_ticket"), Tkt(a="d", id=result.ticket_id))], nav_row(lang, Tkt(a="m"))))
