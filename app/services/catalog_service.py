from __future__ import annotations

import re
from typing import Any

from app.core.constants import BILLING_CYCLES
from app.trusthost.client import TrustHostClient
from app.trusthost.exceptions import TrustHostNotFoundError
from app.trusthost.models import Group, OptionsResponse, Product, PromoResult

_CYCLE_ALIASES = {
    "monthly": "monthly", "quarterly": "quarterly", "semiannually": "semiannually",
    "semi-annually": "semiannually", "semiannual": "semiannually", "annually": "annually", "annual": "annually",
    "yearly": "annually",
}


def normalize_cycle(value: str | None) -> str | None:
    if not value:
        return None
    return _CYCLE_ALIASES.get(re.sub(r"[\s_]", "", value.strip().lower()))


def _scalar_price(v: Any) -> str | None:
    """Return a display string for a price value if it is a plain number/string, else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str) and v.strip():
        return v.strip()
    if isinstance(v, dict):
        for key in ("price", "amount", "total", "recurring"):
            inner = _scalar_price(v.get(key))
            if inner:
                return inner
    return None


def cycle_prices(product: Product) -> dict[str, str]:
    """Extract {cycle: price-string} from `pricing`.

    The documentation does not define the shape of `pricing`, so this is deliberately tolerant:
    dict keyed by cycle (any capitalisation), values scalar or a dict with price/amount/total.
    Returns {} when nothing recognisable is present – callers then fall back to the four documented cycles.
    """
    pricing = product.pricing
    found: dict[str, str] = {}
    if isinstance(pricing, dict):
        for k, v in pricing.items():
            cycle = normalize_cycle(str(k))
            price = _scalar_price(v)
            if cycle and price:
                found[cycle] = price
    elif isinstance(pricing, list):
        for row in pricing:
            if isinstance(row, dict):
                cycle = normalize_cycle(str(row.get("billingcycle") or row.get("cycle") or ""))
                price = _scalar_price(row)
                if cycle and price:
                    found[cycle] = price
    return {c: found[c] for c in BILLING_CYCLES if c in found}


def description_lines(product: Product, limit: int = 8) -> list[str]:
    d = product.description
    items: list[Any]
    if isinstance(d, list):
        items = d
    elif isinstance(d, str) and d.strip():
        items = [x for x in re.split(r"[\r\n]+", d) if x.strip()]
    else:
        items = []
    lines = []
    for it in items:
        text = re.sub(r"<[^>]+>", "", str(it)).strip()
        if text:
            lines.append(text)
    return lines[:limit]


class CatalogService:
    def __init__(self, client: TrustHostClient) -> None:
        self._c = client

    async def groups(self, *, force: bool = False) -> list[Group]:
        return await self._c.list_groups(force=force)

    async def products(self, group_id: int | None = None, *, force: bool = False) -> list[Product]:
        """Orderable products. Hourly products (API 1.3.x) are hidden: they bill the wallet every hour and
        need a dedicated confirmation flow, which the bot does not offer."""
        items = (await self._c.list_products(group_id=group_id, force=force)).products
        return [p for p in items if not p.is_hourly]

    async def product(self, product_id: int) -> Product:
        items = (await self._c.list_products(product_id=product_id)).products
        for p in items:
            if p.id == product_id and not p.is_hourly:
                return p
        raise TrustHostNotFoundError("PRODUCT_NOT_FOUND", status=404)

    async def options(self, product_id: int) -> OptionsResponse:
        return await self._c.get_options(product_id)

    async def validate_promo(self, product_id: int, code: str, cycle: str) -> PromoResult:
        return await self._c.validate_promo(product_id, code, cycle)

    def cycles_for(self, product: Product) -> list[str]:
        """Cycles to offer. API-defined when `pricing` is understood, else all four documented cycles."""
        if product.paytype and product.paytype.lower() != "recurring":
            return ["monthly"]  # one-time / free products: the cycle is irrelevant, API default is used
        return list(cycle_prices(product)) or list(BILLING_CYCLES)
