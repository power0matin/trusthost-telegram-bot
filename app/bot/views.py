"""Pure text rendering (HTML). No I/O. Every string comes from the i18n catalogs."""
from __future__ import annotations

import re
from typing import Any

from app.bot.ui import esc
from app.core.constants import TELEGRAM_TEXT_LIMIT
from app.core.formatting import DASH, Fmt, fit_text, progress_bar, truncate
from app.i18n import has_key, t
from app.i18n.errors import translate_trusthost_error
from app.services.account_service import Dashboard
from app.services.billing_service import PayPreview
from app.services.catalog_service import cycle_prices, description_lines
from app.services.order_service import OrderDraft
from app.services.traffic_service import bucket_points, parse_daily
from app.trusthost.models import (
    Invoice, OrderResult, PayCreditResult, PromoResult, Product, RenewResult, ServerStatus, Service,
    Ticket, TicketDetail, TopupQuote, TopupResult, TrafficUsage, UsageReport, WalletTopupResult,
)


def norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def label(lang: str, kind: str, value: str | None) -> str:
    """Localized label for API enums (service/invoice/ticket status, priority, power state, cycle)."""
    key = f"{kind}.{norm(value)}"
    if value and has_key(lang, key):
        return t(lang, key)
    return esc(value) if value else DASH


def line(lang: str, key: str, value: str, *, code: bool = False) -> str:
    v = f"<code>{esc(value)}</code>" if code else value
    return f"{t(lang, key)}: {v}"


# ------------------------------------------------------------------ dashboard / wallet
def dashboard_text(lang: str, d: Dashboard) -> str:
    f = Fmt(lang)
    n = lambda v: f.int(v) if v is not None else DASH  # noqa: E731
    rows = [t(lang, "dash.title"), "",
            f"💰 {t(lang, 'dash.wallet')}: <b>{f.money(d.balance) if d.balance is not None else DASH}</b>", "",
            f"🖥 {t(lang, 'dash.services')}: <b>{n(d.total)}</b>",
            f"✅ {t(lang, 'dash.active')}: {f.int(d.active)}",
            f"⚠️ {t(lang, 'dash.suspended')}: {f.int(d.suspended)}"]
    if d.other:
        rows.append(f"⏳ {t(lang, 'dash.other')}: {f.int(d.other)}")
    rows += ["", f"📄 {t(lang, 'dash.unpaid')}: <b>{n(d.unpaid)}</b>", "",
             t(lang, "dash.updated", time=f.digits(d.fetched_at.strftime("%Y-%m-%d %H:%M")))]
    if d.partial:
        rows.append(t(lang, "dash.partial"))
    return "\n".join(rows)


def wallet_text(lang: str, balance: float) -> str:
    f = Fmt(lang)
    return "\n".join([t(lang, "wallet.title"), "", f"{t(lang, 'wallet.balance')}:", f"<b>{f.money(balance)}</b>", "",
                      t(lang, "wallet.hint")])


# ------------------------------------------------------------------ servers
def service_summary(lang: str, s: Service) -> str:
    f = Fmt(lang)
    ip = f"<code>{esc(s.display_ip)}</code>" if s.display_ip else (f"<code>{esc(s.domain)}</code>" if s.domain else DASH)
    return (f"🖥 <b>{esc(s.product_name or t(lang, 'srv.unnamed'))}</b>  <code>#{s.id}</code>\n"
            f"   {label(lang, 'svc', s.status)} · {ip}\n"
            f"   {t(lang, 'lbl.next_due')}: {f.date(s.nextduedate)}")


def servers_list_text(lang: str, items: list[Service], page: int, pages: int, total: int, mode: str) -> str:
    title = t(lang, "srv.pick_usage" if mode == "u" else "srv.list_title")
    if not items:
        return f"{title}\n\n{t(lang, 'srv.none')}"
    f = Fmt(lang)
    rows = [title, t(lang, "srv.count_page", total=f.int(total), page=f.int(page + 1), pages=f.int(pages)), ""]
    rows += [service_summary(lang, s) + "\n" for s in items]
    return fit_text(rows, TELEGRAM_TEXT_LIMIT)


def server_detail_text(lang: str, s: Service) -> str:
    f = Fmt(lang)
    rows = [f"🖥 <b>{esc(s.product_name or t(lang, 'srv.unnamed'))}</b>", "", label(lang, "svc", s.status),
            line(lang, "lbl.id", str(s.id), code=True)]
    if s.servertype:
        rows.append(line(lang, "lbl.type", s.servertype, code=True))
    if s.domain:
        rows.append(line(lang, "lbl.domain", s.domain, code=True))
    if s.display_ip:
        rows.append(line(lang, "lbl.ip", s.display_ip, code=True))
    if s.assignedips and s.assignedips.strip() and s.assignedips.strip() != (s.dedicatedip or ""):
        rows.append(line(lang, "lbl.assigned_ips", s.assignedips.replace("\n", ", "), code=True))
    rows += ["", line(lang, "lbl.billing", label(lang, "cycle", s.billingcycle)),
             line(lang, "lbl.price", f.money(s.amount) if s.amount is not None else DASH),
             line(lang, "lbl.next_due", f.date(s.nextduedate))]
    return "\n".join(rows)


def status_text(lang: str, s: Service | None, st: ServerStatus) -> str:
    f = Fmt(lang)
    title = s.product_name if s else ""
    rows = [f"📊 <b>{t(lang, 'status.title')}</b> · <code>#{st.service_id}</code>"]
    if title:
        rows.append(esc(title))
    rows += ["", line(lang, "lbl.status", label(lang, "svc", st.service_status)),
             line(lang, "lbl.power", label(lang, "pow", st.power_state)),
             "",
             f"{t(lang, 'lbl.cpu')}: {f.int(st.cpu)} vCPU" if st.cpu is not None else f"{t(lang, 'lbl.cpu')}: {DASH}",
             f"{t(lang, 'lbl.ram')}: {f.ram(st.ram_mb)}",
             f"{t(lang, 'lbl.disk')}: {f.num(st.disk_gb, 1)} GB" if st.disk_gb is not None else f"{t(lang, 'lbl.disk')}: {DASH}",
             line(lang, "lbl.ip", st.ip or DASH, code=bool(st.ip)), "",
             t(lang, "status.updated", time=f.now())]
    return "\n".join(rows)


def power_menu_text(lang: str, s: Service | None) -> str:
    name = f"\n{esc(s.product_name)}" if s else ""
    return f"{t(lang, 'power.title')}{name}\n\n{t(lang, 'power.hint')}"


def power_confirm_text(lang: str, action: str, s: Service | None) -> str:
    name = esc(s.product_name) if s else ""
    return f"{t(lang, 'warn.title')}\n\n{t(lang, f'power.confirm_{action}')}\n\n🖥 {name}\n\n{t(lang, 'warn.sure')}"


def power_progress_text(lang: str, action: str) -> str:
    return t(lang, "power.sent", action=t(lang, f"power.act_{action}"))


def power_result_text(lang: str, action: str, final: ServerStatus | None, reached: bool | None) -> str:
    f = Fmt(lang)
    act = t(lang, f"power.act_{action}")
    if final is None:
        return t(lang, "power.unverified", action=act)
    state = label(lang, "pow", final.power_state)
    if reached is True:
        return t(lang, "power.confirmed", action=act, state=state, time=f.now())
    if reached is None:  # reboot – state alone cannot prove a restart happened
        return t(lang, "power.reboot_note", state=state, time=f.now())
    return t(lang, "power.not_confirmed", action=act, state=state)


# ------------------------------------------------------------------ traffic / usage
def traffic_text(lang: str, tr: TrafficUsage) -> str:
    f = Fmt(lang)
    unit = tr.unit or "GiB"
    rows = [f"🌐 <b>{t(lang, 'traffic.title')}</b> · <code>#{tr.service_id}</code>", ""]
    if tr.unlimited or tr.limit_gb is None:
        rows += [f"{t(lang, 'lbl.used')}: <b>{f.gb(tr.used_gb, unit)}</b>", t(lang, "traffic.unlimited")]
    else:
        rows += [f"{t(lang, 'lbl.used')}:", f"<b>{f.num(tr.used_gb)} / {f.num(tr.limit_gb, 0)} {unit}</b>", "",
                 f"{t(lang, 'lbl.remaining')}:", f"{f.gb(tr.remaining_gb, unit)}", "",
                 f"{t(lang, 'lbl.usage')}:", f"{progress_bar(tr.percent_used)} {f.pct(tr.percent_used)}"]
    rows += ["", f"{t(lang, 'lbl.download')}: {f.gb(tr.download_gb, unit)}",
             f"{t(lang, 'lbl.upload')}: {f.gb(tr.upload_gb, unit)}", "",
             f"{t(lang, 'lbl.period')}: {f.date(tr.period_start)} → {f.date(tr.period_end) if tr.period_end else t(lang, 'traffic.open')}",
             f"{t(lang, 'lbl.data_status')}: {label(lang, 'data', tr.data_status)}",
             f"{t(lang, 'lbl.last_sync')}: {f.dt(tr.last_synced_at)}", "",
             t(lang, "traffic.note")]
    return "\n".join(rows)


def _chart(points: list[Any], width: int = 12) -> str:
    peak = max((p.inbound for p in points), default=0) or 1
    out = []
    for p in points:
        n = int(round(p.inbound / peak * width))
        out.append(f"{p.label[-11:]:<11} {'█' * n}{'·' * (width - n)} {p.inbound:.1f}")
    return "<pre>" + "\n".join(out) + "</pre>"


def usage_text(lang: str, u: UsageReport, days: int) -> str:
    f = Fmt(lang)
    rows = [f"📈 <b>{t(lang, 'usage.title', days=f.int(days))}</b> · <code>#{u.service_id}</code>", "",
            line(lang, "lbl.status", label(lang, "svc", u.service_status))]
    r = u.resources
    if r and r.available:
        rows += [line(lang, "lbl.power", label(lang, "pow", r.power_state)), "",
                 f"{t(lang, 'lbl.cpu')}: {f.int(r.cpu_cores)} vCPU · {f.int(r.cpu_usage_mhz)} MHz",
                 f"{t(lang, 'lbl.ram')}: {f.ram(r.ram_used_mb)} / {f.ram(r.ram_mb)} ({f.pct(r.ram_percent)})",
                 f"{t(lang, 'lbl.disk')}: {f.num(r.disk_used_gb, 1)} / {f.num(r.disk_gb, 0)} GB",
                 f"{t(lang, 'lbl.uptime')}: {f.duration(r.uptime_seconds)}"]
    else:
        rows += ["", t(lang, "usage.res_unavailable")]
    tr = u.traffic
    if tr:
        unit = tr.unit or "GiB"
        rows += ["", f"<b>{t(lang, 'usage.traffic_period')}</b>",
                 f"{t(lang, 'lbl.download')}: {f.gb(tr.inbound_gb, unit)} ({t(lang, 'usage.counted')})",
                 f"{t(lang, 'lbl.upload')}: {f.gb(tr.outbound_gb, unit)}"]
        if tr.unlimited or tr.limit_gb is None:
            rows.append(t(lang, "traffic.unlimited"))
        else:
            rows.append(f"{t(lang, 'lbl.quota')}: {f.num(tr.limit_gb, 0)} {unit} · {progress_bar(tr.percent_used)} {f.pct(tr.percent_used)}")
    pts = bucket_points(parse_daily(u.daily_traffic))
    rows.append("")
    if pts:
        unit = (u.daily_traffic.unit if u.daily_traffic else "GiB") or "GiB"
        rows += [f"<b>{t(lang, 'usage.daily', unit=esc(unit))}</b>", _chart(pts)]
    elif u.daily_traffic and u.daily_traffic.items:
        rows.append(t(lang, "usage.daily_unrecognised"))
    else:
        rows.append(t(lang, "usage.daily_none"))
    return fit_text(rows, TELEGRAM_TEXT_LIMIT)


# ------------------------------------------------------------------ top-up / renew
def promo_error_text(lang: str, code: str | None, message: str | None = None) -> str:
    return translate_trusthost_error(code or "PROMO_INVALID", lang)


def topup_quote_text(lang: str, q: TopupQuote, svc: Service | None, promo_code: str | None) -> str:
    f = Fmt(lang)
    rows = [f"➕ <b>{t(lang, 'topup.title')}</b> · <code>#{q.service_id}</code>"]
    if svc:
        rows.append(esc(svc.product_name))
    rows += ["", t(lang, "topup.hint")]
    if promo_code:
        if q.promo and q.promo.valid:
            rows += ["", f"🏷 {t(lang, 'promo.applied', code=esc(promo_code))}"]
        else:
            rows += ["", f"⚠️ {promo_error_text(lang, q.promo.error if q.promo else None)}",
                     t(lang, "promo.prices_undiscounted")]
    if not q.options:
        rows += ["", t(lang, "topup.none")]
    return "\n".join(rows)


def topup_option_label(lang: str, o: Any) -> str:
    f = Fmt(lang)
    size = f"{f.int(o.gb)} GB" if o.gb < 1000 or o.gb % 1000 else f"{f.int(o.gb // 1000)} TB"
    return f"{size} — {f.money(o.total)}"


def topup_confirm_text(lang: str, gb: int, opt: Any, promo_code: str | None, svc: Service | None) -> str:
    f = Fmt(lang)
    rows = [f"➕ <b>{t(lang, 'topup.confirm_title')}</b>", ""]
    if svc:
        rows.append(f"🖥 {esc(svc.product_name)} · <code>#{svc.id}</code>")
    rows += [f"{t(lang, 'lbl.volume')}: <b>{f.int(gb)} GB</b>", "",
             f"{t(lang, 'lbl.original')}: {f.money(opt.price)}",
             f"{t(lang, 'lbl.discount')}: {f.money(opt.discount)}",
             f"{t(lang, 'lbl.final')}: <b>{f.money(opt.total)}</b>"]
    if promo_code:
        rows.append(f"🏷 {esc(promo_code)}")
    rows += ["", t(lang, "topup.invoice_note")]
    return "\n".join(rows)


def topup_result_text(lang: str, r: TopupResult) -> str:
    f = Fmt(lang)
    paid = (r.status or "").lower() == "paid"
    rows = [f"✅ <b>{t(lang, 'topup.created')}</b>", "",
            f"{t(lang, 'lbl.invoice')}: <code>#{r.invoice_id}</code>",
            f"{t(lang, 'lbl.volume')}: {f.int(r.gb)} GB",
            f"{t(lang, 'lbl.original')}: {f.money(r.price)}",
            f"{t(lang, 'lbl.discount')}: {f.money(r.discount)}",
            f"{t(lang, 'lbl.final')}: <b>{f.money(r.total)}</b>",
            f"{t(lang, 'lbl.status')}: {label(lang, 'inv', r.status)}"]
    if paid:
        rows += ["", t(lang, "topup.paid_now")]
    return "\n".join(rows)


def renew_start_text(lang: str, s: Service | None) -> str:
    f = Fmt(lang)
    rows = [f"🔄 <b>{t(lang, 'renew.title')}</b>"]
    if s:
        rows += [f"🖥 {esc(s.product_name)} · <code>#{s.id}</code>",
                 f"{t(lang, 'lbl.next_due')}: {f.date(s.nextduedate)}",
                 f"{t(lang, 'lbl.price')}: {f.money(s.amount)} ({label(lang, 'cycle', s.billingcycle)})"]
    rows += ["", t(lang, "renew.explain")]
    return "\n".join(rows)


def renew_confirm_text(lang: str, s: Service | None, promo: str | None) -> str:
    rows = [f"🔄 <b>{t(lang, 'renew.confirm_title')}</b>", ""]
    if s:
        rows.append(f"🖥 {esc(s.product_name)} · <code>#{s.id}</code>")
    rows.append(f"🏷 {esc(promo)}" if promo else t(lang, "renew.no_promo"))
    rows += ["", t(lang, "renew.invoice_note")]
    return "\n".join(rows)


def renew_result_text(lang: str, r: RenewResult) -> str:
    f = Fmt(lang)
    rows = [f"{'✅' if r.created else 'ℹ️'} <b>{t(lang, 'renew.created' if r.created else 'renew.existing')}</b>", "",
            f"{t(lang, 'lbl.invoice')}: <code>#{r.invoice_id}</code>",
            f"{t(lang, 'lbl.amount')}: <b>{f.money(r.total)}</b>"]
    legacy_due = r.extra_value("due_date")  # API 1.1.x only; 1.3.x no longer reports a due date here
    if legacy_due:
        rows.append(f"{t(lang, 'lbl.due')}: {f.date(legacy_due)}")
    if r.promo and r.promo.get("code"):
        rows.append(f"🏷 {esc(r.promo['code'])}: −{f.money(r.promo.get('discount'))}")
    if (r.status or "").lower() == "paid":
        rows.append(f"✅ {label(lang, 'inv', r.status)}")
    return "\n".join(rows)


def wallet_topup_confirm_text(lang: str, amount: int) -> str:
    return t(lang, "wtop.confirm", amount=f"<b>{Fmt(lang).money(amount)}</b>")


def wallet_topup_created_text(lang: str, r: WalletTopupResult) -> str:
    return t(lang, "wtop.created", invoice=f"<code>#{r.invoice_id}</code>", amount=f"<b>{Fmt(lang).money(r.amount)}</b>")


def ticket_close_confirm_text(lang: str, tid: str) -> str:
    return t(lang, "tkt.close_confirm", tid=esc(tid))


# ------------------------------------------------------------------ invoices / payment
def invoice_card(lang: str, inv: Invoice, *, detailed: bool = False) -> str:
    f = Fmt(lang)
    rows = [f"📄 <b>{t(lang, 'lbl.invoice')} #{esc(inv.invoicenum or inv.id)}</b> · <code>{inv.id}</code>",
            f"{label(lang, 'inv', inv.status)}",
            f"{t(lang, 'lbl.amount')}: <b>{f.money(inv.total)}</b>"]
    if inv.credit:
        rows.append(f"{t(lang, 'lbl.credit')}: {f.money(inv.credit)}")
    rows.append(f"{t(lang, 'lbl.date')}: {f.date(inv.date)} · {t(lang, 'lbl.due')}: {f.date(inv.duedate)}")
    if detailed and inv.is_unpaid and inv.best_url:
        rows.append(t(lang, "inv.pay_hint"))
    return "\n".join(rows)


def invoices_list_text(lang: str, items: list[Invoice], page: int, pages: int, total: int, status_key: str) -> str:
    f = Fmt(lang)
    title = f"💳 <b>{t(lang, 'inv.title')}</b> — {t(lang, f'inv.filter_{status_key}')}"
    if not items:
        return f"{title}\n\n{t(lang, 'inv.none')}\n\n{t(lang, 'inv.limit_note')}"
    rows = [title, t(lang, "srv.count_page", total=f.int(total), page=f.int(page + 1), pages=f.int(pages)), ""]
    rows += [invoice_card(lang, i) + "\n" for i in items]
    rows.append(t(lang, "inv.limit_note"))
    return fit_text(rows, TELEGRAM_TEXT_LIMIT)


def pay_preview_text(lang: str, p: PayPreview) -> str:
    f = Fmt(lang)
    rows = [f"💰 <b>{t(lang, 'pay.title')}</b>", "",
            f"{t(lang, 'lbl.invoice')}: <code>#{esc(p.invoice.invoicenum or p.invoice.id)}</code>",
            f"{t(lang, 'lbl.amount')}: <b>{f.money(p.payable)}</b>",
            f"{t(lang, 'lbl.wallet')}: {f.money(p.balance)}"]
    if not p.unpaid:
        rows += ["", f"ℹ️ {translate_trusthost_error('INVOICE_NOT_UNPAID', lang)}"]
    elif p.sufficient:
        rows += [f"{t(lang, 'pay.remaining')}: <b>{f.money(p.remaining)}</b>", "", t(lang, "pay.confirm_q")]
    else:
        rows += ["", f"⚠️ {t(lang, 'pay.insufficient', missing=f.money(-p.remaining))}"]
    return "\n".join(rows)


def pay_success_text(lang: str, r: PayCreditResult) -> str:
    f = Fmt(lang)
    return "\n".join([f"✅ <b>{t(lang, 'pay.success')}</b>", "",
                      f"{t(lang, 'lbl.invoice')}: <code>#{r.invoice_id}</code>",
                      f"{t(lang, 'pay.paid_amount')}: <b>{f.money(r.amount_paid)}</b>",
                      f"{t(lang, 'lbl.status')}: {label(lang, 'inv', r.status)}",
                      f"{t(lang, 'lbl.wallet')}: {f.money(r.wallet_balance)}"])


def pay_url_text(lang: str, usdt: bool, amount: float | None) -> str:
    f = Fmt(lang)
    key = "pay.usdt_ready" if usdt else "pay.online_ready"
    rows = [t(lang, key)]
    if amount is not None:
        rows.append(f"{t(lang, 'lbl.amount')}: <b>{f.money(amount)}</b>")
    rows += ["", t(lang, "pay.after_note")]
    return "\n".join(rows)


# ------------------------------------------------------------------ catalog / orders
def groups_text(lang: str, count: int) -> str:
    return f"🛒 <b>{t(lang, 'order.title')}</b>\n\n{t(lang, 'order.pick_group' if count else 'order.no_groups')}"


def products_text(lang: str, group_name: str, items: list[Product], page: int, pages: int) -> str:
    if not items:
        return f"🛒 <b>{esc(group_name)}</b>\n\n{t(lang, 'order.no_products')}"
    f = Fmt(lang)
    return f"🛒 <b>{esc(group_name)}</b>\n{t(lang, 'lbl.page', page=f.int(page + 1), pages=f.int(pages))}\n\n{t(lang, 'order.pick_product')}"


def product_text(lang: str, p: Product) -> str:
    rows = [f"📦 <b>{esc(p.name)}</b>"]
    if p.group_name:
        rows.append(esc(p.group_name))
    desc = description_lines(p)
    if desc:
        rows += [""] + [f"• {esc(d)}" for d in desc]
    prices = cycle_prices(p)
    if prices:
        rows += ["", f"<b>{t(lang, 'order.prices')}</b>"]
        for cyc, price in prices.items():
            rows.append(f"• {label(lang, 'cycle', cyc)}: <code>{esc(price)}</code>")
    rows += ["", t(lang, "order.pick_cycle")]
    return fit_text(rows, TELEGRAM_TEXT_LIMIT)


def promo_block(lang: str, pr: PromoResult | None, code: str | None) -> list[str]:
    f = Fmt(lang)
    if not code:
        return []
    if pr is None:
        return [f"🏷 {esc(code)}"]
    if pr.valid:
        return ["", f"🏷 <b>{esc(code)}</b> ✅",
                f"{t(lang, 'lbl.original')}: {f.money(pr.original_amount)}",
                f"{t(lang, 'lbl.discount')}: {f.money(pr.discount_amount)}",
                f"{t(lang, 'lbl.final')}: <b>{f.money(pr.final_amount)}</b>"]
    return ["", f"🏷 {esc(code)} ❌ {promo_error_text(lang, pr.error)}"]


def order_review_text(lang: str, d: OrderDraft, pr: PromoResult | None, base_price: str | None) -> str:
    f = Fmt(lang)
    rows = [f"🛒 <b>{t(lang, 'order.summary')}</b>", "",
            f"{t(lang, 'lbl.product')}:", esc(d.product_name), "",
            f"{t(lang, 'lbl.billing')}:", label(lang, "cycle", d.cycle)]
    for lab in list(d.config_labels.values()) + list(d.custom_labels.values()):
        rows += ["", esc(lab)]
    if d.hostname:
        rows += ["", f"{t(lang, 'lbl.hostname')}:", f"<code>{esc(d.hostname)}</code>"]
    if d.domain:
        rows += ["", f"{t(lang, 'lbl.domain')}:", f"<code>{esc(d.domain)}</code>"]
    if d.rootpw:
        rows += ["", f"🔑 {t(lang, 'order.pw_set')}"]
    rows += ["", f"{t(lang, 'lbl.gateway')}: {t(lang, 'order.gw_usdt' if d.gateway == 'usdt' else 'order.gw_card')}"]
    rows += promo_block(lang, pr, d.promo)
    if not (pr and pr.valid) and base_price:
        rows += ["", f"{t(lang, 'lbl.price')}: <code>{esc(base_price)}</code>"]
    rows += ["", t(lang, "order.price_note")]
    return fit_text(rows, TELEGRAM_TEXT_LIMIT)


def order_created_text(lang: str, r: OrderResult) -> str:
    f = Fmt(lang)
    rows = [f"{'ℹ️' if r.is_duplicate else '✅'} <b>{t(lang, 'order.duplicate' if r.is_duplicate else 'order.created')}</b>", ""]
    if r.product_name:
        rows.append(f"📦 {esc(r.product_name)}")
    rows += [f"{t(lang, 'lbl.invoice')}: <code>#{r.invoice_id}</code>",
             f"{t(lang, 'lbl.original')}: {f.money((r.total or 0) + (r.discount_amount or 0))}",
             f"{t(lang, 'lbl.discount')}: {f.money(r.discount_amount or 0)}",
             f"{t(lang, 'lbl.final')}: <b>{f.money(r.total)}</b>",
             f"{t(lang, 'lbl.status')}: {label(lang, 'inv', r.status)}", "", t(lang, "order.next_pay")]
    return "\n".join(rows)


# ------------------------------------------------------------------ tickets
def tickets_list_text(lang: str, items: list[Ticket], page: int, pages: int, total: int) -> str:
    f = Fmt(lang)
    title = f"🎫 <b>{t(lang, 'tkt.my')}</b>"
    if not items:
        return f"{title}\n\n{t(lang, 'tkt.none')}"
    rows = [title, t(lang, "srv.count_page", total=f.int(total), page=f.int(page + 1), pages=f.int(pages)), ""]
    for tk in items:
        rows += [f"🎫 <b>#{esc(tk.tid)}</b> — {esc(truncate(tk.subject, 60))}",
                 f"   {label(lang, 'tkt', tk.status)} · {label(lang, 'prio', tk.priority)} · {esc(tk.department or DASH)}",
                 f"   {t(lang, 'lbl.last_reply')}: {f.dt(tk.lastreply or tk.date)}", ""]
    rows.append(t(lang, "tkt.limit_note"))
    return fit_text(rows, TELEGRAM_TEXT_LIMIT)


def ticket_detail_text(lang: str, d: TicketDetail, priority: str | None) -> str:
    f = Fmt(lang)
    tk = d.ticket
    rows = [f"🎫 <b>{t(lang, 'tkt.ticket')} #{esc(tk.tid)}</b>", "",
            f"{t(lang, 'lbl.department')}:", esc(tk.department or DASH), "",
            f"{t(lang, 'lbl.subject')}:", esc(tk.subject), "",
            f"{t(lang, 'lbl.status')}: {label(lang, 'tkt', tk.status)}"]
    if priority:
        rows.append(f"{t(lang, 'lbl.priority')}: {label(lang, 'prio', priority)}")
    rows += [f"{t(lang, 'lbl.date')}: {f.dt(tk.date)}", "", f"<b>{t(lang, 'tkt.original')}</b>",
             f"<blockquote>{esc(truncate(tk.message, 900))}</blockquote>"]
    replies = d.replies[-4:]
    if replies:
        rows += ["", f"<b>{t(lang, 'tkt.replies')}</b>"]
        if len(d.replies) > len(replies):
            rows.append(t(lang, "tkt.earlier_hidden", n=f.int(len(d.replies) - len(replies))))
        for r in replies:
            who = t(lang, "tkt.staff", name=esc(r.admin)) if r.is_staff else t(lang, "tkt.you")
            rows += [f"{who} · {f.dt(r.date)}", f"<blockquote>{esc(truncate(r.message, 700))}</blockquote>"]
    return fit_text(rows, TELEGRAM_TEXT_LIMIT)


def new_ticket_review(lang: str, dept: str, subject: str, message: str, priority: str, service_label: str | None) -> str:
    rows = [f"🎫 <b>{t(lang, 'tkt.review')}</b>", "",
            f"{t(lang, 'lbl.department')}: {esc(dept)}",
            f"{t(lang, 'lbl.subject')}: {esc(subject)}",
            f"{t(lang, 'lbl.priority')}: {label(lang, 'prio', priority)}",
            f"{t(lang, 'tkt.related')}: {esc(service_label) if service_label else t(lang, 'tkt.no_service')}", "",
            f"<blockquote>{esc(truncate(message, 1200))}</blockquote>"]
    return fit_text(rows, TELEGRAM_TEXT_LIMIT)
