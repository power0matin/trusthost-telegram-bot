from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.guard import OperationGuard
from app.services.audit import AuditService
from app.services.notification_service import NotificationService
from app.trusthost.client import TrustHostClient
from app.core.constants import MIN_TOPUP_AMOUNT
from app.services import validators
from app.trusthost.models import Invoice, InvoiceDetail, PayCreditResult, PayUrl, Wallet, WalletTopupResult

HISTORY_LIMIT = 100  # documented maximum page size of GET /invoices


@dataclass(slots=True)
class PayPreview:
    invoice: Invoice
    balance: float
    payable: float
    remaining: float
    sufficient: bool
    add_funds_url: str | None

    @property
    def unpaid(self) -> bool:
        return self.invoice.is_unpaid


class BillingService:
    def __init__(self, client: TrustHostClient, guard: OperationGuard, audit: AuditService,
                 notifier: NotificationService) -> None:
        self._c, self._guard, self._audit, self._notifier = client, guard, audit, notifier

    async def wallet(self, *, force: bool = False) -> Wallet:
        return await self._c.get_wallet(force=force)

    async def invoices(self, status: str | None = None, *, force: bool = False) -> list[Invoice]:
        """The newest `HISTORY_LIMIT` invoices (API 1.3.x paginates; one page of 100 is the bot's view)."""
        return await self._c.list_invoices(status, limit=HISTORY_LIMIT, force=force)

    async def invoice(self, invoice_id: int) -> InvoiceDetail:
        """Always live (`GET /invoices/details`); the API answers 404 for unknown / foreign invoices."""
        return await self._c.get_invoice(invoice_id)

    async def topup(self, user_id: int, amount: int, gateway: str | None = None) -> WalletTopupResult:
        """Issue a wallet top-up invoice. Paid online only; never retried (not idempotent)."""
        if amount < MIN_TOPUP_AMOUNT:
            raise validators.InputError("val.amount", min=MIN_TOPUP_AMOUNT)
        async with self._guard.acquire(f"wallet_topup:{user_id}"):
            result = await self._audit.run(user_id, "WALLET_TOPUP", f"amount={amount}",
                                           lambda: self._c.topup_wallet(amount, gateway))
            await self._notifier.track_invoice(user_id, result.invoice_id, "Unpaid")
            return result

    async def pay_preview(self, invoice_id: int) -> PayPreview:
        inv, wallet = await asyncio.gather(self.invoice(invoice_id), self._c.get_wallet(force=True))
        payable = inv.payable
        return PayPreview(inv, wallet.balance, payable, wallet.balance - payable,
                          wallet.balance >= payable, wallet.add_funds_url)

    async def pay_with_wallet(self, user_id: int, invoice_id: int) -> PayCreditResult:
        async with self._guard.acquire(f"pay:{invoice_id}"):
            return await self._audit.run(user_id, "PAY_INVOICE", f"invoice={invoice_id}",
                                         lambda: self._c.pay_invoice_with_credit(invoice_id))

    async def pay_url(self, invoice_id: int, gateway: str | None = None) -> PayUrl:
        return await self._c.get_pay_url(invoice_id, gateway)
