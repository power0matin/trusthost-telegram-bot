"""Typed views of the documented TrustHost response objects.

Models are permissive (`extra="allow"`): the docs leave some nested shapes open
(e.g. `Product.pricing`), so unknown keys are preserved instead of rejected.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _M(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def extra_value(self, *keys: str) -> Any:
        extra = self.model_extra or {}
        for k in keys:
            if extra.get(k) not in (None, ""):
                return extra[k]
        return None


def _num(v: Any) -> Any:
    if v in ("", None):
        return None
    return v


# ---------------------------------------------------------------- catalog
class Group(_M):
    id: int
    name: str = ""
    headline: str | None = None
    tagline: str | None = None


class Product(_M):
    id: int
    group_id: int | None = None
    group_name: str | None = None
    name: str = ""
    type: str | None = None
    paytype: str | None = None
    description: Any = None
    pricing: Any = None


class PromoResult(_M):
    success: bool = False
    valid: bool = False
    code: str | None = None
    type: str | None = None
    value: float | None = None
    description: str | None = None
    original_amount: float | None = None
    discount_amount: float | None = None
    final_amount: float | None = None
    message: str | None = None
    error: str | None = None


class ProductsResponse(_M):
    products: list[Product] = Field(default_factory=list)
    promo: PromoResult | None = None


class ConfigSubOption(_M):
    id: int | str
    name: str | None = None

    @property
    def label(self) -> str:
        v = self.name or self.extra_value("optionname", "label", "value", "title")
        return str(v) if v not in (None, "") else str(self.id)


class ConfigOption(_M):
    id: int
    name: str = ""
    type: int | str | None = None
    sub_options: list[ConfigSubOption] = Field(default_factory=list)

    @property
    def is_quantity(self) -> bool:
        # WHMCS convention: 4 = quantity. A choice option without sub-options can only be numeric.
        return str(self.type) == "4" or not self.sub_options


class CustomField(_M):
    id: int
    fieldname: str = ""
    fieldtype: str = "text"
    description: str | None = None
    fieldoptions: str | None = None

    @field_validator("fieldtype", mode="before")
    @classmethod
    def _ft(cls, v: Any) -> str:
        return str(v or "text").lower()

    @property
    def choices(self) -> list[str]:
        return [c.strip() for c in (self.fieldoptions or "").split(",") if c.strip()]

    @property
    def required(self) -> bool:
        return bool(self.extra_value("required", "is_required"))


class OptionsResponse(_M):
    config_options: list[ConfigOption] = Field(default_factory=list)
    custom_fields: list[CustomField] = Field(default_factory=list)


# ---------------------------------------------------------------- orders / billing
class OrderResult(_M):
    success: bool = True
    order_id: int | None = None
    invoice_id: int | None = None
    total: float | None = None
    status: str | None = None
    payment_url: str | None = None
    direct_payment_url: str | None = None
    payment_method: str | None = None
    promocode: str | None = None
    discount_amount: float | None = None
    product_name: str | None = None
    domain: str | None = None
    is_duplicate: bool = False
    message: str | None = None

    @property
    def best_url(self) -> str | None:
        return self.direct_payment_url or self.payment_url


class Invoice(_M):
    id: int
    invoicenum: str | None = None
    date: str | None = None
    duedate: str | None = None
    subtotal: float = 0
    credit: float = 0
    total: float = 0
    status: str = ""
    payment_url: str | None = None
    direct_payment_url: str | None = None

    @field_validator("invoicenum", mode="before")
    @classmethod
    def _inv(cls, v: Any) -> Any:
        return None if v is None else str(v)

    @field_validator("subtotal", "credit", "total", mode="before")
    @classmethod
    def _n(cls, v: Any) -> Any:
        return 0 if v in ("", None) else v

    @property
    def best_url(self) -> str | None:
        return self.direct_payment_url or self.payment_url

    @property
    def is_unpaid(self) -> bool:
        return self.status.lower() == "unpaid"

    @property
    def payable(self) -> float:
        """Best estimate of the amount a wallet payment will take."""
        return max(self.total - self.credit, 0) if self.credit else self.total


class PayUrl(_M):
    invoice_id: int | None = None
    gateway: str | None = None
    direct_payment_url: str | None = None
    amount: float | None = None


class PayCreditResult(_M):
    invoice_id: int | None = None
    amount_paid: float | None = None
    status: str | None = None
    wallet_balance: float | None = None
    message: str | None = None


class Wallet(_M):
    balance: float = 0
    add_funds_url: str | None = None


# ---------------------------------------------------------------- services
class Service(_M):
    id: int
    product_name: str = ""
    servertype: str | None = None
    domain: str | None = None
    dedicatedip: str | None = None
    assignedips: str | None = None
    amount: float | None = None
    billingcycle: str | None = None
    nextduedate: str | None = None
    status: str = ""

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> Any:
        return _num(v)

    @property
    def is_active(self) -> bool:
        return self.status.lower() == "active"

    @property
    def is_suspended(self) -> bool:
        return self.status.lower() == "suspended"

    @property
    def display_ip(self) -> str | None:
        return self.dedicatedip or None


class RenewResult(_M):
    service_id: int | None = None
    invoice_id: int | None = None
    total: float | None = None
    due_date: str | None = None
    created: bool = False
    promo: dict[str, Any] | None = None
    message: str | None = None


class ServerStatus(_M):
    service_id: int | None = None
    service_status: str | None = None
    power_state: str = "UNKNOWN"
    cpu: int | None = None
    ram_mb: int | None = None
    disk_gb: float | None = None
    ip: str | None = None


class PowerResult(_M):
    service_id: int | None = None
    action: str | None = None
    message: str | None = None


class TrafficUsage(_M):
    service_id: int | None = None
    unit: str = "GiB"
    used_gb: float = 0
    download_gb: float | None = None
    upload_gb: float | None = None
    limit_gb: float | None = None
    unlimited: bool = False
    remaining_gb: float | None = None
    percent_used: float | None = None
    period_start: str | None = None
    period_end: str | None = None
    data_status: str | None = None
    last_synced_at: str | None = None


class UsageResources(_M):
    available: bool = False
    power_state: str | None = None
    cpu_cores: int | None = None
    cpu_usage_mhz: float | None = None
    ram_mb: float | None = None
    ram_used_mb: float | None = None
    ram_percent: float | None = None
    disk_gb: float | None = None
    disk_used_gb: float | None = None
    uptime_seconds: int | None = None


class UsageTraffic(_M):
    unit: str = "GiB"
    inbound_gb: float | None = None
    outbound_gb: float | None = None
    billable: str | None = None
    limit_gb: float | None = None
    unlimited: bool = False
    remaining_gb: float | None = None
    percent_used: float | None = None
    period_start: str | None = None
    period_end: str | None = None
    data_status: str | None = None
    last_synced_at: str | None = None


class DailyTraffic(_M):
    unit: str = "GiB"
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)


class UsageReport(_M):
    service_id: int | None = None
    service_status: str | None = None
    resources: UsageResources | None = None
    traffic: UsageTraffic | None = None
    daily_traffic: DailyTraffic | None = None


class TopupOption(_M):
    gb: int
    price: float = 0
    discount: float = 0
    total: float = 0

    @field_validator("price", "discount", "total", mode="before")
    @classmethod
    def _n(cls, v: Any) -> Any:
        return 0 if v in ("", None) else v


class TopupPromo(_M):
    valid: bool = False
    code: str | None = None
    error: str | None = None
    message: str | None = None


class TopupQuote(_M):
    service_id: int | None = None
    currency: str | None = None
    options: list[TopupOption] = Field(default_factory=list)
    promo: TopupPromo | None = None


class TopupResult(_M):
    service_id: int | None = None
    gb: int | None = None
    invoice_id: int | None = None
    price: float | None = None
    discount: float | None = None
    total: float | None = None
    status: str | None = None
    message: str | None = None


# ---------------------------------------------------------------- tickets
class Ticket(_M):
    id: int
    tid: str = ""
    department: str | None = None
    subject: str = ""
    status: str = ""
    priority: str | None = None
    lastreply: str | None = None
    date: str | None = None

    @field_validator("tid", mode="before")
    @classmethod
    def _tid(cls, v: Any) -> str:
        return "" if v is None else str(v)


class TicketInfo(_M):
    id: int
    tid: str = ""
    department: str | None = None
    subject: str = ""
    status: str = ""
    message: str = ""
    date: str | None = None

    @field_validator("tid", mode="before")
    @classmethod
    def _tid(cls, v: Any) -> str:
        return "" if v is None else str(v)


class TicketReply(_M):
    id: int | None = None
    admin: str | None = None
    name: str | None = None
    message: str = ""
    date: str | None = None

    @property
    def is_staff(self) -> bool:
        return bool(self.admin)


class TicketDetail(_M):
    ticket: TicketInfo
    replies: list[TicketReply] = Field(default_factory=list)


class Department(_M):
    id: int
    name: str = ""
    description: str | None = None


class CreateTicketResult(_M):
    ticket_id: int
    tid: str = ""
    message: str | None = None

    @field_validator("tid", mode="before")
    @classmethod
    def _tid(cls, v: Any) -> str:
        return "" if v is None else str(v)
