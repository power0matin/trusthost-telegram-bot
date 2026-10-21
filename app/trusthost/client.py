"""Asynchronous TrustHost Customer API client.

* All authentication lives here (X-Reseller-Key / X-Reseller-Secret headers).
* `success` is always checked – HTTP 200 alone is never trusted.
* Sliding-window limiter + `Retry-After` cooldown protect the 60 req/min limit.
* Concurrent identical GETs are coalesced (single-flight); short TTL cache for slow-changing data.
* POSTs are never retried after the request may have reached the server.
"""
from __future__ import annotations

import asyncio
import base64
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.cache import TTLCache
from app.core.constants import (
    CANCEL_TYPES, GATEWAYS, ORDER_BILLING_CYCLES, TTL_CATALOG, TTL_DEPARTMENTS, TTL_INVOICES, TTL_SERVICES,
    TTL_TICKETS, TTL_WALLET,
)
from app.core.logging import get_logger, log_event
from app.core.security import register_secret
from app.trusthost.exceptions import (
    TrustHostAPIError, TrustHostConnectionError, TrustHostProtocolError, TrustHostRateLimitError,
    build_api_error,
)
from app.trusthost.models import (
    CancelResult, CreateTicketResult, Department, Group, Invoice, InvoiceDetail, InvoicesPage, OptionsResponse,
    OrderResult, PayCreditResult, PayUrl, PowerResult, ProductsResponse, PromoResult, RenewResult, ServerStatus,
    Service, ServiceCredentials, ServiceDetail, Ticket, TicketDetail, TopupQuote, TopupResult, TrafficUsage,
    UsageReport, Wallet, WalletTopupResult,
)

log = get_logger("trusthost.client")

# Classification filters accepted by GET /catalog/groups, /catalog/products and /services (API 1.3.x).
# Values are passed through untouched: an unknown value is rejected by the API with 400 INVALID_<FIELD>.
FILTER_FIELDS = ("category", "location", "plan_type", "billing", "country", "city", "cpu_type")
MAX_ATTACHMENT_BYTES = 1_000_000  # conservative local cap; the docs only say the web server limits the body

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class SlidingWindowLimiter:
    """Allows `max_calls` per `period` seconds. Refuses (instead of blocking for ages) past `max_wait`."""

    def __init__(self, max_calls: int, period: float = 60.0, *, clock: Clock = time.monotonic,
                 sleep: Sleep = asyncio.sleep, max_wait: float = 15.0) -> None:
        self.max_calls, self.period, self.max_wait = max_calls, period, max_wait
        self._clock, self._sleep = clock, sleep
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                wait = self.period - (now - self._calls[0])
                if wait > self.max_wait:
                    raise TrustHostRateLimitError(max(1, math.ceil(wait)), local=True)
                await self._sleep(wait)


class TrustHostClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        *,
        timeout: float = 15.0,
        max_requests_per_minute: int = 50,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        register_secret(api_key)
        register_secret(api_secret)
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=timeout,
            transport=transport,
            headers={
                "X-Reseller-Key": api_key,
                "X-Reseller-Secret": api_secret,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        self._clock, self._sleep = clock, sleep
        self._max_retries = max_retries
        self._limiter = SlidingWindowLimiter(max_requests_per_minute, clock=clock, sleep=sleep)
        self._cache = TTLCache(clock)
        self._inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._blocked_until = 0.0
        self.last_ok_at: float | None = None  # wall-clock epoch of last successful call
        self.last_latency_ms: int | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ cache control
    def invalidate(self, *paths: str) -> None:
        """Drop cached entries whose route starts with one of `paths` (e.g. '/invoices')."""
        self._cache.invalidate(*(f"GET {p}" for p in paths))

    # ------------------------------------------------------------------ transport
    @staticmethod
    def _key(path: str, params: dict[str, Any] | None) -> str:
        q = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        return f"GET {path}?{q}"

    async def _get(self, path: str, params: dict[str, Any] | None = None, *, ttl: float = 0,
                   force: bool = False) -> dict[str, Any]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = self._key(path, params)
        if ttl and not force:
            hit = self._cache.get(key)
            if hit is not None:
                return hit
        fut = self._inflight.get(key)
        if fut is None:
            fut = asyncio.ensure_future(self._send("GET", path, params=params))
            self._inflight[key] = fut
            fut.add_done_callback(lambda f, k=key: self._release(k, f))
        data = await asyncio.shield(fut)
        if ttl:
            self._cache.set(key, data, ttl)
        return data

    def _release(self, key: str, fut: asyncio.Future[dict[str, Any]]) -> None:
        self._inflight.pop(key, None)
        if not fut.cancelled():
            fut.exception()  # mark retrieved; callers see it through shield()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        body = {k: v for k, v in body.items() if v is not None}
        return await self._send("POST", path, body=body)

    async def _send(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                    body: dict[str, Any] | None = None) -> dict[str, Any]:
        attempt = 0
        while True:
            attempt += 1
            remaining = self._blocked_until - self._clock()
            if remaining > 0:
                raise TrustHostRateLimitError(max(1, math.ceil(remaining)), local=True)
            await self._limiter.acquire()
            started = self._clock()
            try:
                resp = await self._http.request(method, path.lstrip("/"), params=params, json=body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Request provably never reached the server → safe to retry any method.
                self._log(method, path, None, started, error=type(exc).__name__)
                if attempt <= self._max_retries:
                    await self._sleep(0.5 * 2 ** (attempt - 1))
                    continue
                raise TrustHostConnectionError("TrustHost is unreachable") from None
            except httpx.HTTPError as exc:
                self._log(method, path, None, started, error=type(exc).__name__)
                if method == "GET" and attempt <= self._max_retries:
                    await self._sleep(0.5 * 2 ** (attempt - 1))
                    continue
                raise TrustHostConnectionError("TrustHost request failed") from None

            status = resp.status_code
            payload: Any
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            code = payload.get("error") if isinstance(payload, dict) else None
            self._log(method, path, status, started, error=code)

            if status == 429:
                retry_after = self._retry_after(resp)
                self._blocked_until = self._clock() + retry_after
                raise TrustHostRateLimitError(retry_after, payload=payload if isinstance(payload, dict) else None)
            if status >= 500 and method == "GET" and attempt <= self._max_retries:
                await self._sleep(0.5 * 2 ** (attempt - 1))
                continue
            if not isinstance(payload, dict):
                if status >= 500:
                    raise build_api_error(status, {})
                raise TrustHostProtocolError("Unexpected non-JSON response from TrustHost")

            if status == 200 and payload.get("success") is True:
                self.last_ok_at = time.time()
                return payload
            # Anything else is a failure, including HTTP 200 with success:false (or a missing flag).
            if status == 200 and "success" not in payload:
                raise TrustHostProtocolError("Response lacks the documented `success` field")
            raise build_api_error(status if status != 200 else 200, payload, self._retry_after(resp, default=None))

    @staticmethod
    def _retry_after(resp: httpx.Response, default: int | None = 60) -> int | None:
        raw = resp.headers.get("Retry-After")
        try:
            return max(1, min(int(raw), 3600)) if raw else default
        except ValueError:
            return default

    def _log(self, method: str, path: str, status: int | None, started: float, error: str | None = None) -> None:
        ms = int((self._clock() - started) * 1000)
        self.last_latency_ms = ms
        log_event(log, "trusthost_api_call", method=method, endpoint=path, status=status,
                  duration_ms=ms, error_code=error)

    # ------------------------------------------------------------------ catalog
    @staticmethod
    def _filters(filters: dict[str, Any]) -> dict[str, Any]:
        unknown = set(filters) - set(FILTER_FIELDS)
        if unknown:
            raise TypeError(f"Unsupported filter(s): {', '.join(sorted(unknown))}")
        return {k: v for k, v in filters.items() if v not in (None, "")}

    async def list_groups(self, *, force: bool = False, **filters: Any) -> list[Group]:
        d = await self._get("/catalog/groups", self._filters(filters), ttl=TTL_CATALOG, force=force)
        return [Group.model_validate(x) for x in d.get("groups", [])]

    async def list_products(self, *, group_id: int | None = None, product_id: int | None = None,
                           promocode: str | None = None, billingcycle: str | None = None,
                           force: bool = False, **filters: Any) -> ProductsResponse:
        params = {"group_id": group_id, "product_id": product_id, "promocode": promocode,
                  "billingcycle": billingcycle if promocode else None, **self._filters(filters)}
        d = await self._get("/catalog/products", params, ttl=0 if promocode else TTL_CATALOG, force=force)
        return ProductsResponse.model_validate(d)

    async def get_options(self, product_id: int, *, force: bool = False) -> OptionsResponse:
        d = await self._get("/catalog/options", {"product_id": product_id}, ttl=TTL_CATALOG, force=force)
        return OptionsResponse.model_validate(d)

    # ------------------------------------------------------------------ orders
    async def validate_promo(self, product_id: int, promocode: str, billingcycle: str = "monthly") -> PromoResult:
        """Always HTTP 200; returns a PromoResult with valid=False + error code on rejection."""
        try:
            d = await self._post("/orders/validate-promo", {
                "product_id": product_id, "promocode": promocode, "billingcycle": billingcycle})
        except TrustHostAPIError as exc:
            if exc.status == 200 and exc.payload.get("valid") is False or exc.code.startswith("PROMO_") \
                    or exc.code in {"EMPTY_PROMO", "PRODUCT_NOT_FOUND"}:
                return PromoResult.model_validate({**exc.payload, "success": False, "valid": False, "error": exc.code})
            raise
        return PromoResult.model_validate(d)

    async def create_order(self, *, product_id: int, billingcycle: str = "monthly", promocode: str | None = None,
                           payment_method: str | None = None, configoptions: dict[str, Any] | None = None,
                           customfields: dict[str, Any] | None = None, domain: str | None = None,
                           hostname: str | None = None, rootpw: str | None = None) -> OrderResult:
        if billingcycle not in ORDER_BILLING_CYCLES:
            raise ValueError(f"Unsupported billing cycle: {billingcycle!r}")
        if payment_method is not None and payment_method not in GATEWAYS:
            raise ValueError(f"Unsupported payment method: {payment_method!r}")
        d = await self._post("/orders/create", {
            "product_id": product_id, "billingcycle": billingcycle, "promocode": promocode or None,
            "payment_method": payment_method, "configoptions": configoptions or None,
            "customfields": customfields or None, "domain": domain or None,
            "hostname": hostname or None, "rootpw": rootpw or None})
        self.invalidate("/invoices", "/wallet")
        return OrderResult.model_validate(d)

    # ------------------------------------------------------------------ billing
    async def list_invoices_page(self, status: str | None = None, *, page: int | None = None,
                                 limit: int | None = None, force: bool = False) -> InvoicesPage:
        """One page of invoices, newest first. Documented bounds: limit 1..100 (default 20), page >= 1."""
        if limit is not None and not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if page is not None and page < 1:
            raise ValueError("page must be >= 1")
        d = await self._get("/invoices", {"status": status, "page": page, "limit": limit},
                            ttl=TTL_INVOICES, force=force)
        return InvoicesPage.model_validate(d)

    async def list_invoices(self, status: str | None = None, *, page: int | None = None,
                            limit: int | None = None, force: bool = False) -> list[Invoice]:
        return (await self.list_invoices_page(status, page=page, limit=limit, force=force)).invoices

    async def get_invoice(self, invoice_id: int) -> InvoiceDetail:
        d = await self._get("/invoices/details", {"invoice_id": invoice_id}, force=True)
        invoice = d.get("invoice")
        if not isinstance(invoice, dict):
            raise TrustHostProtocolError("Response lacks the documented `invoice` object")
        return InvoiceDetail.model_validate(invoice)

    async def get_pay_url(self, invoice_id: int, gateway: str | None = None) -> PayUrl:
        if gateway is not None and gateway not in GATEWAYS:
            raise ValueError(f"Unsupported gateway: {gateway!r}")
        d = await self._get("/invoices/pay-url", {"invoice_id": invoice_id, "gateway": gateway}, force=True)
        return PayUrl.model_validate(d)

    async def pay_invoice_with_credit(self, invoice_id: int) -> PayCreditResult:
        try:
            d = await self._post("/invoices/pay-credit", {"invoice_id": invoice_id})
        finally:
            self.invalidate("/invoices", "/wallet", "/services")
        return PayCreditResult.model_validate(d)

    async def get_wallet(self, *, force: bool = False) -> Wallet:
        d = await self._get("/wallet", ttl=TTL_WALLET, force=force)
        return Wallet.model_validate(d)

    async def topup_wallet(self, amount: int, gateway: str | None = None) -> WalletTopupResult:
        """Issue a wallet top-up invoice (paid online – never from the wallet itself). Not retried."""
        if gateway is not None and gateway not in GATEWAYS:
            raise ValueError(f"Unsupported gateway: {gateway!r}")
        try:
            d = await self._post("/wallet/topup", {"amount": amount, "gateway": gateway})
        finally:
            self.invalidate("/invoices")
        return WalletTopupResult.model_validate(d)

    # ------------------------------------------------------------------ services
    async def list_services(self, *, force: bool = False, status: str | None = None,
                            **filters: Any) -> list[Service]:
        params = {"status": status, **self._filters(filters)}
        d = await self._get("/services", params, ttl=TTL_SERVICES, force=force)
        return [Service.model_validate(x) for x in d.get("services", [])]

    async def get_service(self, service_id: int) -> ServiceDetail:
        d = await self._get("/services/details", {"service_id": service_id}, force=True)
        service = d.get("service")
        if not isinstance(service, dict):
            raise TrustHostProtocolError("Response lacks the documented `service` object")
        return ServiceDetail.model_validate(service)

    async def get_credentials(self, service_id: int) -> ServiceCredentials:
        """Login credentials. Never cached; the password is registered for log redaction."""
        d = await self._get("/services/credentials", {"service_id": service_id}, force=True)
        creds = ServiceCredentials.model_validate(d)
        register_secret(creds.password)
        return creds

    async def cancel_service(self, service_id: int, cancel_type: str = "End of Billing Period",
                             reason: str | None = None) -> CancelResult:
        if cancel_type not in CANCEL_TYPES:
            raise ValueError(f"Unsupported cancellation type: {cancel_type!r}")
        try:
            d = await self._post("/services/cancel", {"service_id": service_id, "type": cancel_type,
                                                       "reason": reason or None})
        finally:
            self.invalidate("/services")
        return CancelResult.model_validate(d)

    async def renew_service(self, service_id: int, promocode: str | None = None,
                            gateway: str | None = None) -> RenewResult:
        if gateway is not None and gateway not in GATEWAYS:
            raise ValueError(f"Unsupported gateway: {gateway!r}")
        try:
            d = await self._post("/services/renew", {"service_id": service_id, "promocode": promocode or None,
                                                       "gateway": gateway})
        finally:
            self.invalidate("/invoices")
        return RenewResult.model_validate(d)

    async def get_service_status(self, service_id: int) -> ServerStatus:
        d = await self._get("/services/status", {"service_id": service_id}, force=True)
        return ServerStatus.model_validate(d)

    async def power_service(self, service_id: int, action: str) -> PowerResult:
        d = await self._post("/services/power", {"service_id": service_id, "action": action})
        return PowerResult.model_validate(d)

    async def get_traffic(self, service_id: int) -> TrafficUsage:
        d = await self._get("/services/traffic", {"service_id": service_id}, force=True)
        return TrafficUsage.model_validate(d)

    async def get_usage(self, service_id: int, days: int = 30) -> UsageReport:
        d = await self._get("/services/usage", {"service_id": service_id, "days": days}, ttl=10)
        return UsageReport.model_validate(d)

    async def get_topup_quote(self, service_id: int, promocode: str | None = None) -> TopupQuote:
        d = await self._get("/services/traffic-topup/quote",
                            {"service_id": service_id, "promocode": promocode}, force=True)
        return TopupQuote.model_validate(d)

    async def create_topup(self, service_id: int, gb: int, promocode: str | None = None) -> TopupResult:
        try:
            d = await self._post("/services/traffic-topup",
                                 {"service_id": service_id, "gb": gb, "promocode": promocode or None})
        finally:
            self.invalidate("/invoices", "/services")
        return TopupResult.model_validate(d)

    # ------------------------------------------------------------------ tickets
    async def list_tickets(self, *, force: bool = False) -> list[Ticket]:
        d = await self._get("/tickets", ttl=TTL_TICKETS, force=force)
        return [Ticket.model_validate(x) for x in d.get("tickets", [])]

    async def list_departments(self, *, force: bool = False) -> list[Department]:
        d = await self._get("/tickets/departments", ttl=TTL_DEPARTMENTS, force=force)
        return [Department.model_validate(x) for x in d.get("departments", [])]

    async def get_ticket(self, ticket_id: int) -> TicketDetail:
        d = await self._get("/tickets/details", {"ticket_id": ticket_id}, force=True)
        return TicketDetail.model_validate(d)

    @staticmethod
    def _attachment(attachment: tuple[str, bytes] | None) -> dict[str, str] | None:
        """(file name, raw bytes) -> the documented inline `{name, content_b64}` object."""
        if attachment is None:
            return None
        name, data = attachment
        if not name or not data:
            raise ValueError("Attachment needs a name and content")
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError("Attachment is too large")
        return {"name": name, "content_b64": base64.b64encode(data).decode("ascii")}

    async def create_ticket(self, subject: str, message: str, *, dept_id: int | None = None,
                            priority: str = "Medium", service_id: int | None = None,
                            attachment: tuple[str, bytes] | None = None) -> CreateTicketResult:
        d = await self._post("/tickets/create", {
            "subject": subject, "message": message, "dept_id": dept_id, "priority": priority,
            "service_id": service_id or None, "attachment": self._attachment(attachment)})
        self.invalidate("/tickets")
        return CreateTicketResult.model_validate(d)

    async def reply_ticket(self, ticket_id: int, message: str,
                           attachment: tuple[str, bytes] | None = None) -> None:
        await self._post("/tickets/reply", {"ticket_id": ticket_id, "message": message,
                                            "attachment": self._attachment(attachment)})
        self.invalidate("/tickets")

    async def close_ticket(self, ticket_id: int) -> None:
        try:
            await self._post("/tickets/close", {"ticket_id": ticket_id})
        finally:
            self.invalidate("/tickets")
