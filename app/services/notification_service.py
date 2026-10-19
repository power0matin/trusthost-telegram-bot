"""Polling-based notifications (the API has no webhooks) – tickets, services, invoices.

One cached list request per kind per cycle is shared across users. State is persisted so restarts
never produce duplicate notifications, and the very first poll only seeds state (no spam).
"""
from __future__ import annotations

import html

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import Inv, Srv, Tkt
from app.core.formatting import Fmt
from app.core.logging import get_logger, log_event
from app.database.repository import Repository, UserRecord
from app.i18n import t
from app.trusthost.client import TrustHostClient
from app.trusthost.exceptions import TrustHostError

log = get_logger("notifications")
MAX_TICKET_DETAIL_FETCHES = 5


class NotificationService:
    def __init__(self, bot: Bot, repo: Repository, client: TrustHostClient, default_language: str = "en") -> None:
        self._bot, self._repo, self._c = bot, repo, client
        self._default = default_language

    # ------------------------------------------------------------ silent state registration
    async def track_invoice(self, user_id: int, invoice_id: int | None, status: str | None) -> None:
        if invoice_id:
            await self._repo.set_states(user_id, "payments", {str(invoice_id): status or "Unpaid"})

    async def sync_ticket(self, user_id: int, ticket_id: int) -> None:
        """After the user's own reply/create, record the new signature so it is not reported back."""
        try:
            for tk in await self._c.list_tickets(force=True):
                if tk.id == ticket_id:
                    await self._repo.set_states(user_id, "tickets", {str(tk.id): f"{tk.status}|{tk.lastreply or ''}"})
        except TrustHostError:
            pass

    # ------------------------------------------------------------ polling
    async def run_once(self) -> None:
        for user in await self._repo.list_users():
            lang = user.language or self._default
            for kind, fn in (("tickets", self._tickets), ("services", self._services), ("payments", self._payments)):
                if not user.wants(kind):
                    continue
                try:
                    await fn(user, lang)
                except TrustHostError as exc:
                    log_event(log, "notification_poll_failed", kind=kind, error=getattr(exc, "code", type(exc).__name__))
                except Exception:
                    log.exception("notification_poll_crashed")

    async def _diff(self, user: UserRecord, kind: str, current: dict[str, str]) -> tuple[list[tuple[str, str]], bool]:
        """Return ([(resource_id, old_state)] for changed known resources, was_seeded) and persist new state."""
        old = await self._repo.get_states(user.telegram_id, kind)
        seeded = await self._repo.get_last_poll(user.telegram_id, kind) is not None
        changed = [(rid, old[rid]) for rid, sig in current.items() if rid in old and old[rid] != sig]
        to_store = {rid: sig for rid, sig in current.items() if old.get(rid) != sig}
        await self._repo.set_states(user.telegram_id, kind, to_store)
        await self._repo.touch_poll(user.telegram_id, kind)
        return (changed if seeded else []), seeded

    async def _send(self, user_id: int, text: str, button: InlineKeyboardButton | None = None) -> None:
        markup = InlineKeyboardMarkup(inline_keyboard=[[button]]) if button else None
        try:
            await self._bot.send_message(user_id, text, reply_markup=markup)
        except Exception:
            log.exception("notification_send_failed")

    async def _tickets(self, user: UserRecord, lang: str) -> None:
        tickets = await self._c.list_tickets()
        current = {str(tk.id): f"{tk.status}|{tk.lastreply or ''}" for tk in tickets}
        changed, _ = await self._diff(user, "tickets", current)
        by_id = {str(tk.id): tk for tk in tickets}
        for rid, _old in changed[:MAX_TICKET_DETAIL_FETCHES]:
            tk = by_id[rid]
            detail = await self._c.get_ticket(tk.id)
            last = detail.replies[-1] if detail.replies else None
            staff_reply = bool(last and last.is_staff) or tk.status.lower() == "answered"
            if not staff_reply:
                continue
            snippet = html.escape((last.message if last else "")[:300])
            text = t(lang, "notify.ticket_reply", tid=html.escape(tk.tid), subject=html.escape(tk.subject),
                     snippet=snippet or "—")
            await self._send(user.telegram_id, text,
                             InlineKeyboardButton(text=t(lang, "btn.view_ticket"),
                                                  callback_data=Tkt(a="d", id=tk.id).pack()))

    async def _services(self, user: UserRecord, lang: str) -> None:
        services = await self._c.list_services()
        current = {str(s.id): s.status for s in services}
        changed, _ = await self._diff(user, "services", current)
        by_id = {str(s.id): s for s in services}
        for rid, old in changed:
            s = by_id[rid]
            text = t(lang, "notify.service_status", name=html.escape(s.product_name), id=s.id,
                     old=html.escape(old), new=html.escape(s.status))
            await self._send(user.telegram_id, text,
                             InlineKeyboardButton(text=t(lang, "btn.view_server"),
                                                  callback_data=Srv(a="d", id=s.id).pack()))

    async def _payments(self, user: UserRecord, lang: str) -> None:
        invoices = await self._c.list_invoices()
        current = {str(i.id): i.status for i in invoices}
        changed, _ = await self._diff(user, "payments", current)
        by_id = {str(i.id): i for i in invoices}
        f = Fmt(lang)
        for rid, old in changed:
            inv = by_id[rid]
            key = "notify.invoice_paid" if inv.status.lower() == "paid" else "notify.invoice_status"
            text = t(lang, key, id=inv.id, old=html.escape(old), new=html.escape(inv.status), amount=f.money(inv.total))
            await self._send(user.telegram_id, text,
                             InlineKeyboardButton(text=t(lang, "btn.view_invoice"),
                                                  callback_data=Inv(a="d", id=inv.id).pack()))

