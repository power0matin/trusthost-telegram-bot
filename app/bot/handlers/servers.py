from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot import views
from app.bot.callbacks import Pow, Srv, Use
from app.bot.keyboards.servers import (
    power_confirm_kb, power_done_kb, power_menu_kb, server_detail_kb, servers_list_kb, status_kb,
    traffic_kb, usage_kb,
)
from app.bot.ui import Event, fail, loading, show
from app.core.constants import DEFAULT_USAGE_DAYS, POWER_ACTIONS, POWER_CONFIRM_ACTIONS
from app.core.guard import OperationInProgress
from app.services.container import Hub
from app.trusthost.exceptions import TrustHostError

router = Router(name="servers")


async def show_servers(event: Event, hub: Hub, lang: str, page: int = 0, mode: str = "d", force: bool = False) -> None:
    try:
        services = await hub.servers.services(force=force)
    except TrustHostError as exc:
        await fail(event, lang, exc, None)
        return
    markup, items, page, pages = servers_list_kb(lang, services, page, mode)
    await show(event, views.servers_list_text(lang, items, page, pages, len(services), mode), markup)


@router.callback_query(Srv.filter(F.a == "l"))
async def cb_list(cb: CallbackQuery, callback_data: Srv, hub: Hub, lang: str) -> None:
    await show_servers(cb, hub, lang, callback_data.p, callback_data.m[:1] or "d", force=callback_data.m.endswith("!"))


@router.callback_query(Srv.filter(F.a == "d"))
async def cb_detail(cb: CallbackQuery, callback_data: Srv, hub: Hub, lang: str) -> None:
    try:
        svc = await hub.servers.service(callback_data.id, force=bool(callback_data.p))
    except TrustHostError as exc:
        await fail(cb, lang, exc, Srv(a="l"))
        return
    await show(cb, views.server_detail_text(lang, svc), server_detail_kb(lang, svc))


@router.callback_query(Srv.filter(F.a == "st"))
async def cb_status(cb: CallbackQuery, callback_data: Srv, hub: Hub, lang: str) -> None:
    sid = callback_data.id
    await loading(cb, lang)
    try:
        svc = await hub.servers.service(sid)
        st = await hub.servers.status(sid)
    except TrustHostError as exc:
        await fail(cb, lang, exc, Srv(a="d", id=sid))
        return
    await show(cb, views.status_text(lang, svc, st), status_kb(lang, sid))


@router.callback_query(Srv.filter(F.a == "tr"))
async def cb_traffic(cb: CallbackQuery, callback_data: Srv, hub: Hub, lang: str) -> None:
    sid = callback_data.id
    await loading(cb, lang)
    try:
        tr = await hub.traffic.traffic(sid)
    except TrustHostError as exc:
        await fail(cb, lang, exc, Srv(a="d", id=sid))
        return
    await show(cb, views.traffic_text(lang, tr), traffic_kb(lang, sid))


async def _usage(cb: CallbackQuery, hub: Hub, lang: str, sid: int, days: int) -> None:
    await loading(cb, lang)
    try:
        report = await hub.traffic.usage(sid, days)
    except TrustHostError as exc:
        await fail(cb, lang, exc, Srv(a="d", id=sid))
        return
    await show(cb, views.usage_text(lang, report, days), usage_kb(lang, sid, days))


@router.callback_query(Srv.filter(F.a == "us"))
async def cb_usage_default(cb: CallbackQuery, callback_data: Srv, hub: Hub, lang: str) -> None:
    await _usage(cb, hub, lang, callback_data.id, DEFAULT_USAGE_DAYS)


@router.callback_query(Use.filter())
async def cb_usage_days(cb: CallbackQuery, callback_data: Use, hub: Hub, lang: str) -> None:
    await _usage(cb, hub, lang, callback_data.id, callback_data.d)


# ------------------------------------------------------------------ power
@router.callback_query(Srv.filter(F.a == "pw"))
async def cb_power_menu(cb: CallbackQuery, callback_data: Srv, hub: Hub, lang: str) -> None:
    try:
        svc = await hub.servers.service(callback_data.id)
    except TrustHostError as exc:
        await fail(cb, lang, exc, Srv(a="l"))
        return
    await show(cb, views.power_menu_text(lang, svc), power_menu_kb(lang, svc.id))


@router.callback_query(Pow.filter(F.a == "ask"))
async def cb_power_ask(cb: CallbackQuery, callback_data: Pow, hub: Hub, lang: str) -> None:
    sid, action = callback_data.id, callback_data.act
    if action not in POWER_ACTIONS:
        return
    if action not in POWER_CONFIRM_ACTIONS:  # powering on is harmless – no confirmation needed
        await _do_power(cb, hub, lang, sid, action)
        return
    try:
        svc = await hub.servers.service(sid)  # re-check ownership before offering a destructive action
    except TrustHostError as exc:
        await fail(cb, lang, exc, Srv(a="l"))
        return
    await show(cb, views.power_confirm_text(lang, action, svc), power_confirm_kb(lang, sid, action))


@router.callback_query(Pow.filter(F.a == "do"))
async def cb_power_do(cb: CallbackQuery, callback_data: Pow, hub: Hub, lang: str) -> None:
    if callback_data.act in POWER_ACTIONS:
        await _do_power(cb, hub, lang, callback_data.id, callback_data.act)


async def _do_power(cb: CallbackQuery, hub: Hub, lang: str, sid: int, action: str) -> None:
    async def on_sent(_: object) -> None:
        # The API accepts the command asynchronously – never claim success yet.
        await show(cb, views.power_progress_text(lang, action), None)

    try:
        await loading(cb, lang, "processing")
        outcome = await hub.servers.power_and_verify(cb.from_user.id, sid, action, on_sent)
    except OperationInProgress:
        return  # a double click: the first request is still being handled
    except TrustHostError as exc:
        await fail(cb, lang, exc, Srv(a="pw", id=sid))
        return
    await show(cb, views.power_result_text(lang, action, outcome.final, outcome.reached), power_done_kb(lang, sid))
