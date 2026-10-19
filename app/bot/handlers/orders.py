"""Catalog browsing and the dynamic order wizard.

Nothing here knows about specific products, OSes or locations – steps are built from
GET /catalog/options at runtime.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import views
from app.bot.callbacks import Cat, Cfg, Ord
from app.bot.keyboards import orders as kbo
from app.bot.keyboards.billing import pay_options_kb
from app.bot.keyboards.common import kb, nav_row
from app.bot.states import OrderStates
from app.bot.ui import Event, esc, fail, loading, show
from app.core.constants import CYCLE_CODES
from app.core.guard import OperationInProgress
from app.i18n import t
from app.services import validators
from app.services.catalog_service import cycle_prices
from app.services.container import Hub
from app.services.order_service import OrderDraft, build_steps, find_field, find_option
from app.trusthost.exceptions import TrustHostError

router = Router(name="orders")


# ------------------------------------------------------------------ draft helpers
async def _load(state: FSMContext) -> OrderDraft | None:
    raw = (await state.get_data()).get("order")
    return OrderDraft.from_dict(raw) if raw else None


async def _save(state: FSMContext, draft: OrderDraft) -> None:
    await state.update_data(order=draft.to_dict())


async def _expired(event: Event, lang: str) -> None:
    await show(event, t(lang, "order.expired"), kb(nav_row(lang)))


# ------------------------------------------------------------------ browsing
async def show_groups(event: Event, hub: Hub, lang: str) -> None:
    await loading(event, lang)
    try:
        groups = await hub.catalog.groups()
    except TrustHostError as exc:
        await fail(event, lang, exc, None)
        return
    await show(event, views.groups_text(lang, len(groups)), kbo.groups_kb(lang, groups))


@router.callback_query(Cat.filter(F.a == "g"))
async def cb_groups(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await show_groups(cb, hub, lang)


@router.callback_query(Cat.filter(F.a == "l"))
async def cb_products(cb: CallbackQuery, callback_data: Cat, hub: Hub, lang: str) -> None:
    await loading(cb, lang)
    try:
        groups = await hub.catalog.groups()
        products = await hub.catalog.products(callback_data.g)
    except TrustHostError as exc:
        await fail(cb, lang, exc, Cat(a="g"))
        return
    name = next((g.name for g in groups if g.id == callback_data.g), t(lang, "order.title"))
    markup, items, page, pages = kbo.products_kb(lang, products, callback_data.p, callback_data.g)
    await show(cb, views.products_text(lang, name, items, page, pages), markup)


@router.callback_query(Cat.filter(F.a == "p"))
async def cb_product(cb: CallbackQuery, callback_data: Cat, hub: Hub, lang: str) -> None:
    await loading(cb, lang)
    try:
        product = await hub.catalog.product(callback_data.pid)
    except TrustHostError as exc:
        await fail(cb, lang, exc, Cat(a="l", g=callback_data.g))
        return
    cycles = hub.catalog.cycles_for(product)
    await show(cb, views.product_text(lang, product), kbo.product_kb(lang, product, cycles, callback_data.g or (product.group_id or 0)))


@router.callback_query(Cat.filter(F.a == "c"))
async def cb_cycle(cb: CallbackQuery, callback_data: Cat, state: FSMContext, hub: Hub, lang: str) -> None:
    cycle = CYCLE_CODES.get(callback_data.cy)
    if cycle is None:
        return
    await loading(cb, lang)
    try:
        product = await hub.catalog.product(callback_data.pid)
    except TrustHostError as exc:
        await fail(cb, lang, exc, Cat(a="g"))
        return
    await state.clear()
    await _save(state, OrderDraft(product_id=product.id, product_name=product.name, cycle=cycle))
    await render_step(cb, state, hub, lang)


# ------------------------------------------------------------------ wizard
async def render_step(event: Event, state: FSMContext, hub: Hub, lang: str, *, new: bool = False) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(event, lang)
        return
    try:
        options = await hub.catalog.options(draft.product_id)
    except TrustHostError as exc:
        await fail(event, lang, exc, Cat(a="g"))
        return
    steps = build_steps(options)
    if draft.step >= len(steps):
        await render_extras(event, state, lang, new=new)
        return
    kind, rid = steps[draft.step]
    head = t(lang, "order.step_head", n=draft.step + 1, total=len(steps), product=esc(draft.product_name))
    if kind == "o":
        opt = find_option(options, rid)
        if opt is None:
            return
        if opt.is_quantity:
            await state.set_state(OrderStates.quantity)
            await show(event, f"{head}\n\n<b>{esc(opt.name)}</b>\n{t(lang, 'order.enter_quantity')}", kbo.text_step_kb(lang), new=new)
        else:
            await state.set_state(None)
            await show(event, f"{head}\n\n<b>{esc(opt.name)}</b>\n{t(lang, 'order.choose')}", kbo.choice_step_kb(lang, opt), new=new)
        return
    fld = find_field(options, rid)
    if fld is None:
        return
    desc = f"\n<i>{esc(fld.description)}</i>" if fld.description else ""
    text = f"{head}\n\n<b>{esc(fld.fieldname)}</b>{desc}"
    if fld.fieldtype in ("dropdown", "tickbox") and (fld.choices or fld.fieldtype == "tickbox"):
        await state.set_state(None)
        await show(event, f"{text}\n{t(lang, 'order.choose')}", kbo.field_choice_kb(lang, fld), new=new)
    else:
        await state.set_state(OrderStates.custom)
        await show(event, f"{text}\n{t(lang, 'order.enter_text')}", kbo.text_step_kb(lang, skippable=not fld.required), new=new)


async def _advance(event: Event, state: FSMContext, hub: Hub, lang: str, draft: OrderDraft, *, new: bool) -> None:
    draft.step += 1
    await _save(state, draft)
    await render_step(event, state, hub, lang, new=new)


@router.callback_query(Cfg.filter(F.a == "s"))
async def cb_pick_sub(cb: CallbackQuery, callback_data: Cfg, state: FSMContext, hub: Hub, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(cb, lang)
        return
    options = await hub.catalog.options(draft.product_id)
    opt = find_option(options, callback_data.o)
    sub = next((s for s in (opt.sub_options if opt else []) if str(s.id) == str(callback_data.v)), None)
    if opt is None or sub is None:  # stale button: option changed upstream
        await render_step(cb, state, hub, lang)
        return
    draft.config[str(opt.id)] = int(callback_data.v)
    draft.config_labels[str(opt.id)] = f"{opt.name}: {sub.label}"
    await _advance(cb, state, hub, lang, draft, new=False)


@router.callback_query(Cfg.filter(F.a.in_({"d", "y", "n"})))
async def cb_pick_field(cb: CallbackQuery, callback_data: Cfg, state: FSMContext, hub: Hub, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(cb, lang)
        return
    options = await hub.catalog.options(draft.product_id)
    fld = find_field(options, callback_data.o)
    if fld is None:
        await render_step(cb, state, hub, lang)
        return
    if callback_data.a == "d":
        if callback_data.v >= len(fld.choices):
            await render_step(cb, state, hub, lang)
            return
        value = fld.choices[callback_data.v]
    elif callback_data.a == "y":
        value = "on"
    else:
        value = ""
    if value:
        draft.custom[str(fld.id)] = value
        draft.custom_labels[str(fld.id)] = f"{fld.fieldname}: {value if value != 'on' else '✓'}"
    await _advance(cb, state, hub, lang, draft, new=False)


@router.callback_query(Cfg.filter(F.a == "k"))
async def cb_skip(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(cb, lang)
        return
    await _advance(cb, state, hub, lang, draft, new=False)


@router.callback_query(Cfg.filter(F.a == "b"))
async def cb_back(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(cb, lang)
        return
    if draft.step <= 0:
        await state.set_state(None)
        await cb_product(cb, Cat(a="p", pid=draft.product_id), hub, lang)
        return
    draft.step -= 1
    await _save(state, draft)
    await render_step(cb, state, hub, lang)


@router.message(StateFilter(OrderStates.quantity), F.text, ~F.text.startswith("/"))
async def msg_quantity(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(message, lang)
        return
    options = await hub.catalog.options(draft.product_id)
    steps = build_steps(options)
    kind, rid = steps[draft.step] if draft.step < len(steps) else ("", 0)
    opt = find_option(options, rid) if kind == "o" else None
    if opt is None:
        await render_step(message, state, hub, lang, new=True)
        return
    try:
        qty = validators.quantity(message.text or "")
    except validators.InputError as exc:
        await message.answer(t(lang, exc.key), reply_markup=kbo.text_step_kb(lang))
        return
    draft.config[str(opt.id)] = qty
    draft.config_labels[str(opt.id)] = f"{opt.name}: {qty}"
    await _advance(message, state, hub, lang, draft, new=True)


@router.message(StateFilter(OrderStates.custom), F.text, ~F.text.startswith("/"))
async def msg_custom(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(message, lang)
        return
    options = await hub.catalog.options(draft.product_id)
    steps = build_steps(options)
    kind, rid = steps[draft.step] if draft.step < len(steps) else ("", 0)
    fld = find_field(options, rid) if kind == "f" else None
    if fld is None:
        await render_step(message, state, hub, lang, new=True)
        return
    sensitive = fld.fieldtype == "password"
    try:
        value = validators.custom_text(message.text or "")
    except validators.InputError as exc:
        await message.answer(t(lang, exc.key), reply_markup=kbo.text_step_kb(lang, skippable=not fld.required))
        return
    if sensitive:
        await _try_delete(message)
    draft.custom[str(fld.id)] = value
    draft.custom_labels[str(fld.id)] = f"{fld.fieldname}: {'••••••' if sensitive else value}"
    await _advance(message, state, hub, lang, draft, new=True)


async def _try_delete(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass  # Telegram may refuse (e.g. message too old); nothing else to do


# ------------------------------------------------------------------ extras
async def render_extras(event: Event, state: FSMContext, lang: str, *, new: bool = False) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(event, lang)
        return
    await state.set_state(None)
    rows = [f"⚙️ <b>{t(lang, 'order.extras_title')}</b>", "", t(lang, "order.extras_hint")]
    if draft.hostname:
        rows.append(f"🖥 <code>{esc(draft.hostname)}</code>")
    if draft.domain:
        rows.append(f"🌐 <code>{esc(draft.domain)}</code>")
    if draft.promo:
        rows.append(f"🏷 {esc(draft.promo)}")
    await show(event, "\n".join(rows), kbo.extras_kb(lang, draft), new=new)


_PROMPTS = {"host": (OrderStates.hostname, "order.prompt_hostname", "clr_host"),
            "dom": (OrderStates.domain, "order.prompt_domain", "clr_dom"),
            "pw": (OrderStates.rootpw, "order.prompt_password", "clr_pw"),
            "promo": (OrderStates.promo, "order.prompt_promo", "clr_promo")}


@router.callback_query(Ord.filter(F.a == "extras"))
async def cb_extras(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    await render_extras(cb, state, lang)


@router.callback_query(Ord.filter(F.a == "steps"))
async def cb_steps(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    await render_step(cb, state, hub, lang)


@router.callback_query(Ord.filter(F.a.in_(set(_PROMPTS))))
async def cb_prompt(cb: CallbackQuery, callback_data: Ord, state: FSMContext, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(cb, lang)
        return
    st, key, clr = _PROMPTS[callback_data.a]
    current = {"host": draft.hostname, "dom": draft.domain, "pw": draft.rootpw, "promo": draft.promo}[callback_data.a]
    await state.set_state(st)
    await show(cb, t(lang, key), kbo.extras_prompt_kb(lang, clr if current else None))


@router.callback_query(Ord.filter(F.a.in_({"clr_host", "clr_dom", "clr_pw", "clr_promo"})))
async def cb_clear(cb: CallbackQuery, callback_data: Ord, state: FSMContext, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(cb, lang)
        return
    field = {"clr_host": "hostname", "clr_dom": "domain", "clr_pw": "rootpw", "clr_promo": "promo"}[callback_data.a]
    setattr(draft, field, None)
    await _save(state, draft)
    await render_extras(cb, state, lang)


@router.callback_query(Ord.filter(F.a == "gw"))
async def cb_gateway(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(cb, lang)
        return
    draft.gateway = None if draft.gateway == "usdt" else "usdt"
    await _save(state, draft)
    await render_extras(cb, state, lang)


async def _text_field(message: Message, state: FSMContext, hub: Hub, lang: str, field: str, validate) -> None:  # type: ignore[no-untyped-def]
    draft = await _load(state)
    if draft is None:
        await _expired(message, lang)
        return
    secret = field == "rootpw"
    try:
        value = validate(message.text or "")
    except validators.InputError as exc:
        if secret:
            await _try_delete(message)
        await message.answer(t(lang, exc.key), reply_markup=kbo.extras_prompt_kb(lang, None))
        return
    if secret:
        await _try_delete(message)  # remove the password from the chat history
    setattr(draft, field, value)
    await _save(state, draft)
    await render_extras(message, state, lang, new=True)


@router.message(StateFilter(OrderStates.hostname), F.text, ~F.text.startswith("/"))
async def msg_hostname(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await _text_field(message, state, hub, lang, "hostname", validators.hostname)


@router.message(StateFilter(OrderStates.domain), F.text, ~F.text.startswith("/"))
async def msg_domain(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await _text_field(message, state, hub, lang, "domain", validators.domain)


@router.message(StateFilter(OrderStates.rootpw), F.text, ~F.text.startswith("/"))
async def msg_rootpw(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    await _text_field(message, state, hub, lang, "rootpw", validators.root_password)


@router.message(StateFilter(OrderStates.promo), F.text, ~F.text.startswith("/"))
async def msg_promo(message: Message, state: FSMContext, hub: Hub, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(message, lang)
        return
    try:
        code = validators.promo_code(message.text or "")
        result = await hub.catalog.validate_promo(draft.product_id, code, draft.cycle)
    except validators.InputError as exc:
        await message.answer(t(lang, exc.key), reply_markup=kbo.extras_prompt_kb(lang, None))
        return
    except TrustHostError as exc:
        await fail(message, lang, exc, Ord(a="extras"))
        return
    if not result.valid:
        await message.answer("🏷 ❌ " + views.promo_error_text(lang, result.error), reply_markup=kbo.extras_prompt_kb(lang, None))
        return
    draft.promo = code
    await _save(state, draft)
    await render_extras(message, state, lang, new=True)


# ------------------------------------------------------------------ review / confirm
@router.callback_query(Ord.filter(F.a == "review"))
async def cb_review(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    draft = await _load(state)
    if draft is None:
        await _expired(cb, lang)
        return
    await loading(cb, lang)
    promo_result = None
    try:
        product = await hub.catalog.product(draft.product_id)
        if draft.promo:
            promo_result = await hub.catalog.validate_promo(draft.product_id, draft.promo, draft.cycle)
    except TrustHostError as exc:
        await fail(cb, lang, exc, Ord(a="extras"))
        return
    base = cycle_prices(product).get(draft.cycle)
    can_confirm = not (draft.promo and promo_result and not promo_result.valid)
    await show(cb, views.order_review_text(lang, draft, promo_result, base), kbo.review_kb(lang, can_confirm=can_confirm))


@router.callback_query(Ord.filter(F.a == "confirm"))
async def cb_confirm(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    draft = await _load(state)
    if draft is None:  # already submitted (double click) or session gone
        await _expired(cb, lang)
        return
    try:
        await loading(cb, lang, "processing")
        result = await hub.orders.create(cb.from_user.id, draft)
    except OperationInProgress:
        return
    except TrustHostError as exc:
        await fail(cb, lang, exc, Ord(a="review"), hub=hub)
        return
    except validators.InputError as exc:
        await show(cb, t(lang, exc.key), kb(nav_row(lang, Ord(a="extras"))))
        return
    await state.clear()  # drops the draft incl. the root password from memory
    text = views.order_created_text(lang, result)
    if result.invoice_id and (result.status or "").lower() != "paid":
        await show(cb, text, pay_options_kb(lang, result.invoice_id, result.best_url, None))
    else:
        await show(cb, text, kb(nav_row(lang)))


@router.callback_query(Ord.filter(F.a == "cancel"))
async def cb_cancel_order(cb: CallbackQuery, state: FSMContext, hub: Hub, lang: str) -> None:
    await state.clear()
    await show_groups(cb, hub, lang)
