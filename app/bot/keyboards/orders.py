from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.callbacks import Cat, Cfg, Ord
from app.bot.keyboards.common import Row, btn, cancel_row, kb, nav_row, paginate, pager_row
from app.core.constants import CYCLE_TO_CODE, PAGE_SIZE
from app.i18n import t
from app.services.catalog_service import cycle_prices
from app.services.order_service import OrderDraft
from app.trusthost.models import ConfigOption, CustomField, Group, Product


def groups_kb(lang: str, groups: list[Group]) -> InlineKeyboardMarkup:
    rows = [[btn(f"📁 {g.name}"[:60], Cat(a="l", g=g.id))] for g in groups]
    rows.append(nav_row(lang))
    return kb(*rows)


def products_kb(lang: str, products: list[Product], page: int, group_id: int) -> tuple[InlineKeyboardMarkup, list[Product], int, int]:
    items, page, pages = paginate(products, page, PAGE_SIZE)
    rows: list[Row | None] = []
    for p in items:
        price = next(iter(cycle_prices(p).values()), None)
        rows.append([btn(f"📦 {p.name}" + (f" · {price}" if price else ""), Cat(a="p", pid=p.id, g=group_id))])
    rows.append(pager_row(page, pages, lambda pg: Cat(a="l", g=group_id, p=pg)))
    rows.append(nav_row(lang, Cat(a="g")))
    return kb(*rows), items, page, pages


def product_kb(lang: str, p: Product, cycles: list[str], group_id: int) -> InlineKeyboardMarkup:
    from app.i18n import has_key
    prices = cycle_prices(p)
    rows: list[Row | None] = []
    if len(cycles) == 1 and p.paytype and p.paytype.lower() != "recurring":
        rows.append([btn(t(lang, "order.order_now"), Cat(a="c", pid=p.id, cy=CYCLE_TO_CODE[cycles[0]]))])
    else:
        for c in cycles:
            name = t(lang, f"cycle.{c}") if has_key(lang, f"cycle.{c}") else c
            suffix = f" · {prices[c]}" if c in prices else ""
            rows.append([btn(f"{name}{suffix}", Cat(a="c", pid=p.id, cy=CYCLE_TO_CODE[c]))])
    rows.append(nav_row(lang, Cat(a="l", g=group_id)))
    return kb(*rows)


def choice_step_kb(lang: str, opt: ConfigOption) -> InlineKeyboardMarkup:
    rows: list[Row | None] = []
    pair: Row = []
    for sub in opt.sub_options:
        try:
            sid = int(sub.id)
        except (TypeError, ValueError):
            continue
        pair.append(btn(sub.label[:30], Cfg(a="s", o=opt.id, v=sid)))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([btn(t(lang, "btn.skip_default"), Cfg(a="k"))])
    rows.append([btn(t(lang, "btn.back"), Cfg(a="b")), btn(t(lang, "btn.cancel"), Ord(a="cancel"))])
    return kb(*rows)


def text_step_kb(lang: str, *, skippable: bool = True) -> InlineKeyboardMarkup:
    rows: list[Row | None] = []
    if skippable:
        rows.append([btn(t(lang, "btn.skip"), Cfg(a="k"))])
    rows.append([btn(t(lang, "btn.back"), Cfg(a="b")), btn(t(lang, "btn.cancel"), Ord(a="cancel"))])
    return kb(*rows)


def field_choice_kb(lang: str, f: CustomField) -> InlineKeyboardMarkup:
    rows: list[Row | None] = []
    if f.fieldtype == "tickbox":
        rows.append([btn(t(lang, "btn.yes"), Cfg(a="y", o=f.id)), btn(t(lang, "btn.no"), Cfg(a="n", o=f.id))])
    else:
        for i, choice in enumerate(f.choices):
            rows.append([btn(choice[:40], Cfg(a="d", o=f.id, v=i))])
    if not f.required:
        rows.append([btn(t(lang, "btn.skip"), Cfg(a="k"))])
    rows.append([btn(t(lang, "btn.back"), Cfg(a="b")), btn(t(lang, "btn.cancel"), Ord(a="cancel"))])
    return kb(*rows)


def extras_kb(lang: str, d: OrderDraft) -> InlineKeyboardMarkup:
    mark = lambda v: " ✓" if v else ""  # noqa: E731
    return kb(
        [btn(t(lang, "order.btn_hostname") + mark(d.hostname), Ord(a="host")),
         btn(t(lang, "order.btn_domain") + mark(d.domain), Ord(a="dom"))],
        [btn(t(lang, "order.btn_password") + mark(d.rootpw), Ord(a="pw")),
         btn(t(lang, "order.btn_promo") + mark(d.promo), Ord(a="promo"))],
        [btn(t(lang, "order.btn_gateway", gw=t(lang, "order.gw_usdt" if d.gateway == "usdt" else "order.gw_card")),
             Ord(a="gw"))],
        [btn(t(lang, "order.btn_review"), Ord(a="review"))],
        [btn(t(lang, "btn.back"), Cfg(a="b")), btn(t(lang, "btn.cancel"), Ord(a="cancel"))],
    )


def extras_prompt_kb(lang: str, clear_action: str | None) -> InlineKeyboardMarkup:
    rows: list[Row | None] = []
    if clear_action:
        rows.append([btn(t(lang, "btn.clear"), Ord(a=clear_action))])
    rows.append([btn(t(lang, "btn.back"), Ord(a="extras")), btn(t(lang, "btn.cancel"), Ord(a="cancel"))])
    return kb(*rows)


def review_kb(lang: str, *, can_confirm: bool) -> InlineKeyboardMarkup:
    rows: list[Row | None] = []
    if can_confirm:
        rows.append([btn(t(lang, "btn.confirm_order"), Ord(a="confirm")), btn(t(lang, "btn.cancel"), Ord(a="cancel"))])
    else:
        rows.append([btn(t(lang, "btn.clear_promo"), Ord(a="clr_promo"))])
    rows.append([btn(t(lang, "btn.edit"), Ord(a="extras"))])
    return kb(*rows)
