from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from app.core.formatting import now_tehran
from app.trusthost.client import TrustHostClient
from app.trusthost.exceptions import (
    TrustHostAuthenticationError, TrustHostForbiddenError, TrustHostRateLimitError,
)
from app.trusthost.models import Wallet


@dataclass(slots=True)
class Dashboard:
    balance: float | None
    add_funds_url: str | None
    total: int | None
    active: int
    suspended: int
    other: int
    unpaid: int | None
    fetched_at: datetime
    partial: bool = False


class AccountService:
    def __init__(self, client: TrustHostClient) -> None:
        self._c = client

    async def wallet(self, *, force: bool = False) -> Wallet:
        return await self._c.get_wallet(force=force)

    async def dashboard(self, *, force: bool = False) -> Dashboard:
        """Wallet + services + unpaid invoices = 3 requests (all cached briefly)."""
        results = await asyncio.gather(
            self._c.get_wallet(force=force),
            self._c.list_services(force=force),
            self._c.list_invoices("Unpaid", force=force),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, (TrustHostAuthenticationError, TrustHostForbiddenError, TrustHostRateLimitError)):
                raise r
        if all(isinstance(r, BaseException) for r in results):
            raise results[0]  # type: ignore[misc]
        wallet, services, unpaid = results
        active = suspended = other = 0
        if not isinstance(services, BaseException):
            for s in services:
                if s.is_active:
                    active += 1
                elif s.is_suspended:
                    suspended += 1
                else:
                    other += 1
        return Dashboard(
            balance=None if isinstance(wallet, BaseException) else wallet.balance,
            add_funds_url=None if isinstance(wallet, BaseException) else wallet.add_funds_url,
            total=None if isinstance(services, BaseException) else len(services),
            active=active, suspended=suspended, other=other,
            unpaid=None if isinstance(unpaid, BaseException) else len(unpaid),
            fetched_at=now_tehran(),
            partial=any(isinstance(r, BaseException) for r in results),
        )
