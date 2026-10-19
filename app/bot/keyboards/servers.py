from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.callbacks import NewT, Pow, Ren, Srv, Top, Use
from app.bot.keyboards.common import btn, kb, nav_row, paginate, pager_row
from app.core.constants import PAGE_SIZE, POWER_ACTIONS, USAGE_DAY_CHOICES
from app.i18n import t
from app.trusthost.models import Service

_STATUS_EMOJI = {"active": "✅", "suspended": "⚠️", "pending": "⏳"}


def servers_list_kb(lang: str, services: list[Service], page: int, mode: str) -> tuple[InlineKeyboardMarkup, list[Service], int, int]:
    items, page, pages = paginate(services, page, PAGE_SIZE)
    rows = []
    for s in items:
        emoji = _STATUS_EMOJI.get(s.status.lower(), "❌" if s.status else "🖥")
        name = s.product_name or t(lang, "srv.unnamed")
        action = "us" if mode == "u" else "d"
        rows.append([btn(f"{emoji} {name} · #{s.id}"[:60], Srv(a=action, id=s.id))])
    rows.append(pager_row(page, pages, lambda p: Srv(a="l", p=p, m=mode)))
    rows.append([btn(t(lang, "btn.refresh"), Srv(a="l", p=page, m=mode + "!"))])
    rows.append(nav_row(lang))
    return kb(*rows), items, page, pages


def server_detail_kb(lang: str, s: Service) -> InlineKeyboardMarkup:
    sid = s.id
    b = lambda key, cb: btn(t(lang, key), cb)  # noqa: E731
    return kb(
        [b("btn.status", Srv(a="st", id=sid)), b("btn.usage", Srv(a="us", id=sid))],
        [b("btn.traffic", Srv(a="tr", id=sid)), b("btn.power", Srv(a="pw", id=sid))],
        [b("btn.renew", Ren(a="s", id=sid)), b("btn.topup", Top(a="q", id=sid))],
        [b("btn.support", NewT(a="s", v=sid)), b("btn.refresh", Srv(a="d", id=sid, p=1))],
        nav_row(lang, Srv(a="l")),
    )


def status_kb(lang: str, sid: int) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "btn.refresh"), Srv(a="st", id=sid)), btn(t(lang, "btn.power"), Srv(a="pw", id=sid))],
              nav_row(lang, Srv(a="d", id=sid)))


def traffic_kb(lang: str, sid: int) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "btn.refresh"), Srv(a="tr", id=sid)), btn(t(lang, "btn.topup"), Top(a="q", id=sid))],
              [btn(t(lang, "btn.usage"), Srv(a="us", id=sid))], nav_row(lang, Srv(a="d", id=sid)))


def usage_kb(lang: str, sid: int, days: int) -> InlineKeyboardMarkup:
    days_row = [btn(("✓ " if d == days else "") + t(lang, "usage.days_btn", n=d), Use(id=sid, d=d))
                for d in USAGE_DAY_CHOICES]
    return kb(days_row[:3], days_row[3:], [btn(t(lang, "btn.traffic"), Srv(a="tr", id=sid))],
              nav_row(lang, Srv(a="d", id=sid)))


def power_menu_kb(lang: str, sid: int) -> InlineKeyboardMarkup:
    icons = {"on": "🟢", "off": "🔴", "shutdown": "🟡", "reboot": "🔄"}
    rows = [[btn(f"{icons[a]} {t(lang, f'power.btn_{a}')}", Pow(a="ask", id=sid, act=a))] for a in POWER_ACTIONS]
    rows.append([btn(t(lang, "btn.status"), Srv(a="st", id=sid))])
    rows.append(nav_row(lang, Srv(a="d", id=sid)))
    return kb(*rows)


def power_confirm_kb(lang: str, sid: int, action: str) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, f"power.yes_{action}"), Pow(a="do", id=sid, act=action)),
               btn(t(lang, "btn.no_cancel"), Srv(a="pw", id=sid))])


def power_done_kb(lang: str, sid: int) -> InlineKeyboardMarkup:
    return kb([btn(t(lang, "btn.status"), Srv(a="st", id=sid)), btn(t(lang, "btn.power"), Srv(a="pw", id=sid))],
              nav_row(lang, Srv(a="d", id=sid)))
