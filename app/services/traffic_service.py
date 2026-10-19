from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.core.guard import OperationGuard
from app.services import validators
from app.services.audit import AuditService
from app.services.notification_service import NotificationService
from app.trusthost.client import TrustHostClient
from app.trusthost.exceptions import TrustHostBadRequestError
from app.trusthost.models import DailyTraffic, TopupQuote, TopupResult, TrafficUsage, UsageReport


@dataclass(slots=True)
class DailyPoint:
    label: str
    inbound: float
    outbound: float


def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def parse_daily(daily: DailyTraffic | None) -> list[DailyPoint]:
    """`items` is documented only as `[{}]`; locate date / inbound / outbound by common aliases."""
    if not daily:
        return []
    points: list[DailyPoint] = []
    for it in daily.items:
        label = _first(it, "date", "day", "d")
        inbound = _first(it, "inbound_gb", "download_gb", "inbound", "in_gb", "rx_gb", "in")
        outbound = _first(it, "outbound_gb", "upload_gb", "outbound", "out_gb", "tx_gb", "out")
        try:
            if label is None or inbound is None:
                continue
            points.append(DailyPoint(str(label)[:10], float(inbound), float(outbound or 0)))
        except (TypeError, ValueError):
            continue
    return sorted(points, key=lambda p: p.label)


def bucket_points(points: list[DailyPoint], max_rows: int = 15) -> list[DailyPoint]:
    """Group consecutive days so long ranges still fit one Telegram message."""
    if len(points) <= max_rows:
        return points
    size = math.ceil(len(points) / max_rows)
    out = []
    for i in range(0, len(points), size):
        chunk = points[i:i + size]
        label = chunk[0].label if len(chunk) == 1 else f"{chunk[0].label}+{len(chunk)}d"
        out.append(DailyPoint(label, sum(p.inbound for p in chunk), sum(p.outbound for p in chunk)))
    return out


class TrafficService:
    def __init__(self, client: TrustHostClient, guard: OperationGuard, audit: AuditService,
                 notifier: NotificationService) -> None:
        self._c, self._guard, self._audit, self._notifier = client, guard, audit, notifier

    async def traffic(self, service_id: int) -> TrafficUsage:
        return await self._c.get_traffic(service_id)

    async def usage(self, service_id: int, days: int = 30) -> UsageReport:
        if not 1 <= days <= 90:
            raise validators.InputError("val.days")
        return await self._c.get_usage(service_id, days)

    async def topup_quote(self, service_id: int, promo: str | None = None) -> TopupQuote:
        code = validators.promo_code(promo) if promo else None
        return await self._c.get_topup_quote(service_id, code)

    async def topup_create(self, user_id: int, service_id: int, gb: int, promo: str | None = None) -> TopupResult:
        code = validators.promo_code(promo) if promo else None
        async with self._guard.acquire(f"topup:{service_id}"):
            quote = await self._c.get_topup_quote(service_id, code)  # sizes are API-defined: re-check
            if gb not in {o.gb for o in quote.options}:
                raise TrustHostBadRequestError("TRAFFIC_TIER_UNAVAILABLE", status=400)
            result = await self._audit.run(user_id, "TRAFFIC_TOPUP", f"service={service_id},gb={gb}",
                                           lambda: self._c.create_topup(service_id, gb, code))
            await self._notifier.track_invoice(user_id, result.invoice_id, result.status)
            return result
