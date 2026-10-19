from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.guard import OperationGuard
from app.services.audit import AuditService
from app.trusthost.client import TrustHostClient
from app.trusthost.exceptions import TrustHostNotFoundError
from app.trusthost.models import Invoice, PayCreditResult, PayUrl, Wallet


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
    def __init__(self, client: TrustHostClient, guard: OperationGuard, audit: AuditService) -> None:
        self._c, self._guard, self._audit = client, guard, audit

    async def wallet(self, *, force: bool = False) -> Wallet:
        return await self._c.get_wallet(force=force)

    async def invoices(self, status: str | None = None, *, force: bool = False) -> list[Invoice]:
        """The API returns only the 20 most recent invoices – there is no deeper history."""
        return await self._c.list_invoices(status, force=force)

    async def invoice(self, invoice_id: int, *, force: bool = True) -> Invoice:
        """No single-invoice endpoint exists: search the recent list, then the Unpaid list."""
        for status in (None, "Unpaid"):
            for inv in await self._c.list_invoices(status, force=force):
                if inv.id == invoice_id:
                    return inv
        raise TrustHostNotFoundError("INVOICE_NOT_FOUND", status=404)

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
