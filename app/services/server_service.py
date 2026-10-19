from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.constants import POWER_ACTIONS, POWER_EXPECTED_STATE
from app.core.guard import OperationGuard
from app.services import validators
from app.services.audit import AuditService
from app.services.notification_service import NotificationService
from app.trusthost.client import TrustHostClient
from app.trusthost.exceptions import (
    TrustHostConflictError, TrustHostConnectionError, TrustHostNotFoundError, TrustHostRateLimitError,
)
from app.trusthost.models import PowerResult, RenewResult, ServerStatus, Service

DEFAULT_POLL_DELAYS = (4.0, 6.0, 8.0, 10.0, 12.0)


@dataclass(slots=True)
class PowerOutcome:
    action: str
    sent: PowerResult
    final: ServerStatus | None
    reached: bool | None  # True = expected state confirmed, False = not confirmed in time, None = not verifiable


class ServerService:
    def __init__(self, client: TrustHostClient, guard: OperationGuard, audit: AuditService,
                 notifier: NotificationService, *, poll_delays: tuple[float, ...] = DEFAULT_POLL_DELAYS,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self._c, self._guard, self._audit, self._notifier = client, guard, audit, notifier
        self._delays, self._sleep = poll_delays, sleep

    async def services(self, *, force: bool = False) -> list[Service]:
        return await self._c.list_services(force=force)

    async def service(self, service_id: int, *, force: bool = False) -> Service:
        """Resolve a service from the caller's own account (guards forged callback data)."""
        for s in await self._c.list_services(force=force):
            if s.id == service_id:
                return s
        raise TrustHostNotFoundError("SERVICE_NOT_FOUND", status=404)

    async def status(self, service_id: int) -> ServerStatus:
        return await self._c.get_service_status(service_id)

    async def power_and_verify(
        self, user_id: int, service_id: int, action: str,
        on_sent: Callable[[PowerResult], Awaitable[None]] | None = None,
    ) -> PowerOutcome:
        """Send the (asynchronous) power command, then poll the status with a bounded retry cycle.

        The per-service guard is held for the whole cycle so a double click cannot queue two commands.
        """
        if action not in POWER_ACTIONS:
            raise validators.InputError("val.action")
        async with self._guard.acquire(f"power:{service_id}"):
            sent = await self._audit.run(user_id, f"POWER_{action.upper()}", f"service={service_id}",
                                         lambda: self._c.power_service(service_id, action))
            if on_sent:
                await on_sent(sent)
            expected = POWER_EXPECTED_STATE.get(action)
            final: ServerStatus | None = None
            delays = self._delays if expected else self._delays[:1]  # reboot: one look, state can't prove it
            for delay in delays:
                await self._sleep(delay)
                try:
                    final = await self._c.get_service_status(service_id)
                except TrustHostConflictError:  # BUSY / VM_NOT_READY while the hypervisor is working
                    continue
                except (TrustHostRateLimitError, TrustHostConnectionError):
                    break
                if expected and final.power_state == expected:
                    return PowerOutcome(action, sent, final, True)
            reached = None if expected is None else False
            return PowerOutcome(action, sent, final, reached)

    async def renew(self, user_id: int, service_id: int, promo: str | None = None) -> RenewResult:
        """Returns the existing unpaid renewal invoice or issues one – the API never double-charges."""
        code = validators.promo_code(promo) if promo else None
        async with self._guard.acquire(f"renew:{service_id}"):
            result = await self._audit.run(user_id, "RENEW_SERVICE", f"service={service_id}",
                                           lambda: self._c.renew_service(service_id, code))
            await self._notifier.track_invoice(user_id, result.invoice_id, "Unpaid")
            return result
