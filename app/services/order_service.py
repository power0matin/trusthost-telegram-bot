from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.guard import OperationGuard
from app.services import validators
from app.services.audit import AuditService
from app.services.notification_service import NotificationService
from app.trusthost.client import TrustHostClient
from app.trusthost.models import ConfigOption, CustomField, OptionsResponse, OrderResult


@dataclass
class OrderDraft:
    """In-memory order draft kept in the FSM. `rootpw` lives only here and is dropped after submit."""

    product_id: int
    product_name: str
    cycle: str
    config: dict[str, int] = field(default_factory=dict)          # option id -> sub-option id / quantity
    config_labels: dict[str, str] = field(default_factory=dict)   # option id -> "Name: Choice"
    custom: dict[str, str] = field(default_factory=dict)          # field id -> value
    custom_labels: dict[str, str] = field(default_factory=dict)   # field id -> "Name: shown value"
    hostname: str | None = None
    domain: str | None = None
    rootpw: str | None = None
    promo: str | None = None
    gateway: str | None = None  # None = card (Zarinpal), "usdt" = Tether
    step: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrderDraft:
        return cls(**data)

    def wipe_secrets(self) -> None:
        self.rootpw = None


Step = tuple[str, int]  # ("o", option_id) | ("f", field_id)


def build_steps(options: OptionsResponse) -> list[Step]:
    return [("o", o.id) for o in options.config_options] + [("f", f.id) for f in options.custom_fields]


def find_option(options: OptionsResponse, option_id: int) -> ConfigOption | None:
    return next((o for o in options.config_options if o.id == option_id), None)


def find_field(options: OptionsResponse, field_id: int) -> CustomField | None:
    return next((f for f in options.custom_fields if f.id == field_id), None)


class OrderService:
    def __init__(self, client: TrustHostClient, guard: OperationGuard, audit: AuditService,
                 notifier: NotificationService) -> None:
        self._c, self._guard, self._audit, self._notifier = client, guard, audit, notifier

    @staticmethod
    def payload(draft: OrderDraft) -> dict[str, Any]:
        return {
            "product_id": draft.product_id,
            "billingcycle": draft.cycle,
            "promocode": draft.promo,
            "payment_method": draft.gateway,
            "configoptions": dict(draft.config) or None,
            "customfields": dict(draft.custom) or None,
            "domain": draft.domain,
            "hostname": draft.hostname,
            "rootpw": draft.rootpw,
        }

    async def create(self, user_id: int, draft: OrderDraft) -> OrderResult:
        if draft.hostname:
            validators.hostname(draft.hostname)
        if draft.domain:
            validators.domain(draft.domain)
        async with self._guard.acquire(f"order:{draft.product_id}"):
            try:
                result = await self._audit.run(
                    user_id, "CREATE_ORDER", f"product={draft.product_id}",
                    lambda: self._c.create_order(**self.payload(draft)))
            finally:
                draft.wipe_secrets()
            await self._notifier.track_invoice(user_id, result.invoice_id, result.status)
            return result
