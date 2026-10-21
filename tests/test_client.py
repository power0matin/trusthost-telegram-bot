from __future__ import annotations

import asyncio

import httpx
import pytest

from app.trusthost.client import SlidingWindowLimiter, TrustHostClient
from app.trusthost.exceptions import (
    TrustHostAPIError, TrustHostAuthenticationError, TrustHostBadRequestError, TrustHostConflictError,
    TrustHostConnectionError, TrustHostForbiddenError, TrustHostInsufficientCreditError, TrustHostNotFoundError,
    TrustHostProtocolError, TrustHostRateLimitError, TrustHostServerBusyError, TrustHostServerError,
    TrustHostUnprocessableError,
)
from tests.fakes import API_KEY, API_SECRET, err, ok

BASE = "https://my.trusthost.co/api/v1"


def make(handler, **kw):  # type: ignore[no-untyped-def]
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)

    c = TrustHostClient(BASE, API_KEY, API_SECRET, transport=httpx.MockTransport(handler), sleep=sleep,
                        max_requests_per_minute=kw.pop("rpm", 1000), **kw)
    c.slept = slept  # type: ignore[attr-defined]
    return c


# ------------------------------------------------------------------ success + auth headers
async def test_success_parses_models_and_sends_auth_headers(client, fake):
    wallet = await client.get_wallet(force=True)
    assert wallet.balance == 2_000_000 and wallet.add_funds_url.startswith("https://")
    services = await client.list_services(force=True)
    assert services[0].id == 150 and services[0].amount == 1350000.0 and services[0].is_active
    h = fake.headers_seen[0]
    assert h["x-reseller-key"] == API_KEY and h["x-reseller-secret"] == API_SECRET
    assert h["content-type"].startswith("application/json")


async def test_base_url_path_is_preserved():
    seen = []

    def handler(req):  # type: ignore[no-untyped-def]
        seen.append(str(req.url))
        return httpx.Response(200, json=ok(balance=1, add_funds_url=None))

    c = make(handler)
    await c.get_wallet()
    assert seen == ["https://my.trusthost.co/api/v1/wallet"]


# ------------------------------------------------------------------ success flag is authoritative
async def test_http_200_with_success_false_is_an_error(client, fake):
    fake.invoices[0]["status"] = "Paid"
    with pytest.raises(TrustHostAPIError) as ei:
        await client.get_pay_url(8841)
    assert ei.value.code == "ALREADY_PAID" and ei.value.status == 200


async def test_http_200_without_success_field_is_protocol_error():
    c = make(lambda req: httpx.Response(200, json={"balance": 5}))
    with pytest.raises(TrustHostProtocolError):
        await c.get_wallet()


async def test_non_json_body_is_protocol_error():
    c = make(lambda req: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(TrustHostProtocolError):
        await c.get_wallet()


async def test_validate_promo_returns_result_not_exception(client):
    bad = await client.validate_promo(12, "NOPE", "monthly")
    assert bad.valid is False and bad.error == "PROMO_NOT_FOUND"
    good = await client.validate_promo(12, "WELCOME10", "monthly")
    assert good.valid and good.final_amount == 1215000


# ------------------------------------------------------------------ HTTP status mapping
@pytest.mark.parametrize("status,payload,exc", [
    (401, err("UNAUTHORIZED"), TrustHostAuthenticationError),
    (402, err("INSUFFICIENT_CREDIT"), TrustHostInsufficientCreditError),
    (403, err("API_DISABLED"), TrustHostForbiddenError),
    (403, err("FORBIDDEN"), TrustHostForbiddenError),
    (404, err("SERVICE_NOT_FOUND"), TrustHostNotFoundError),
    (409, err("BUSY"), TrustHostServerBusyError),
    (409, err("VM_NOT_READY"), TrustHostConflictError),
    (409, err("SERVICE_NOT_ACTIVE", service_status="Suspended"), TrustHostConflictError),
    (400, err("INVALID_ACTION"), TrustHostBadRequestError),
    (422, err("PROMO_NOT_APPLICABLE"), TrustHostUnprocessableError),
    (500, err("SERVER_ERROR"), TrustHostServerError),
])
async def test_error_status_mapping(status, payload, exc):
    c = make(lambda req: httpx.Response(status, json=payload), max_retries=0)
    with pytest.raises(exc) as ei:
        await c.get_wallet()
    assert ei.value.status == status and ei.value.code == payload["error"]


async def test_405_is_reported_not_swallowed():
    c = make(lambda req: httpx.Response(405, json=err("METHOD_NOT_ALLOWED")))
    with pytest.raises(TrustHostAPIError) as ei:
        await c.get_wallet()
    assert ei.value.status == 405


async def test_409_not_renewable_is_a_conflict_error(client, fake):
    with pytest.raises(TrustHostConflictError) as ei:
        await client.renew_service(151)
    assert ei.value.code == "NOT_RENEWABLE" and ei.value.status == 409


async def test_str_of_exception_never_contains_message_or_secrets():
    c = make(lambda req: httpx.Response(401, json=err("UNAUTHORIZED", f"bad {API_SECRET}")))
    with pytest.raises(TrustHostAuthenticationError) as ei:
        await c.get_wallet()
    assert API_SECRET not in str(ei.value) and API_SECRET not in repr(ei.value)


# ------------------------------------------------------------------ retries
async def test_get_500_is_retried_with_backoff_then_succeeds():
    n = {"i": 0}

    def handler(req):  # type: ignore[no-untyped-def]
        n["i"] += 1
        return httpx.Response(500, json=err("SERVER_ERROR")) if n["i"] < 3 else httpx.Response(200, json=ok(balance=7))

    c = make(handler, max_retries=2)
    assert (await c.get_wallet()).balance == 7
    assert n["i"] == 3 and c.slept == [0.5, 1.0]


async def test_get_500_gives_up_after_max_retries():
    n = {"i": 0}

    def handler(req):  # type: ignore[no-untyped-def]
        n["i"] += 1
        return httpx.Response(500, json=err("SERVER_ERROR"))

    c = make(handler, max_retries=2)
    with pytest.raises(TrustHostServerError):
        await c.get_wallet()
    assert n["i"] == 3


async def test_post_500_is_never_retried():
    n = {"i": 0}

    def handler(req):  # type: ignore[no-untyped-def]
        n["i"] += 1
        return httpx.Response(500, json=err("SERVER_ERROR"))

    c = make(handler, max_retries=3)
    with pytest.raises(TrustHostServerError):
        await c.pay_invoice_with_credit(1)
    assert n["i"] == 1  # a retried payment could double-charge


async def test_post_read_timeout_is_not_retried_but_connect_error_is():
    calls = {"i": 0}

    def timeout_handler(req):  # type: ignore[no-untyped-def]
        calls["i"] += 1
        raise httpx.ReadTimeout("slow", request=req)

    c = make(timeout_handler, max_retries=2)
    with pytest.raises(TrustHostConnectionError):
        await c.power_service(150, "reboot")
    assert calls["i"] == 1

    calls["i"] = 0

    def conn_handler(req):  # type: ignore[no-untyped-def]
        calls["i"] += 1
        raise httpx.ConnectError("down", request=req)

    c2 = make(conn_handler, max_retries=2)
    with pytest.raises(TrustHostConnectionError):
        await c2.power_service(150, "reboot")
    assert calls["i"] == 3  # request never reached the server → safe to retry


# ------------------------------------------------------------------ 429 / Retry-After
async def test_429_respects_retry_after_and_does_not_hammer_the_api():
    n = {"i": 0}

    def handler(req):  # type: ignore[no-untyped-def]
        n["i"] += 1
        return httpx.Response(429, json=err("RATE_LIMITED"), headers={"Retry-After": "42"})

    t = {"now": 1000.0}
    c = TrustHostClient(BASE, API_KEY, API_SECRET, transport=httpx.MockTransport(handler), clock=lambda: t["now"])
    with pytest.raises(TrustHostRateLimitError) as ei:
        await c.get_wallet()
    assert ei.value.retry_after == 42 and not ei.value.local
    # while cooling down nothing is sent to the network
    with pytest.raises(TrustHostRateLimitError) as ei2:
        await c.list_services()
    assert ei2.value.local and n["i"] == 1 and 1 <= ei2.value.retry_after <= 42
    t["now"] += 43  # cooldown over
    with pytest.raises(TrustHostRateLimitError):
        await c.get_wallet()
    assert n["i"] == 2


async def test_429_is_not_auto_retried_for_post():
    n = {"i": 0}

    def handler(req):  # type: ignore[no-untyped-def]
        n["i"] += 1
        return httpx.Response(429, json=err("RATE_LIMITED"), headers={"Retry-After": "5"})

    c = make(handler, max_retries=3)
    with pytest.raises(TrustHostRateLimitError):
        await c.create_order(product_id=1)
    assert n["i"] == 1


async def test_local_limiter_refuses_instead_of_blocking_for_ages():
    t = {"now": 0.0}
    slept: list[float] = []

    async def sleep(s: float) -> None:
        slept.append(s)
        t["now"] += s

    lim = SlidingWindowLimiter(3, 60, clock=lambda: t["now"], sleep=sleep, max_wait=15)
    for _ in range(3):
        await lim.acquire()
    with pytest.raises(TrustHostRateLimitError) as ei:  # would have to wait 60s > max_wait
        await lim.acquire()
    assert ei.value.local and ei.value.retry_after >= 59
    t["now"] += 50
    await lim.acquire()  # waits ≤ 15s inside the window, allowed
    assert slept and slept[0] <= 15


# ------------------------------------------------------------------ cache + single flight
async def test_ttl_cache_force_and_invalidate(client, fake):
    await client.list_groups()
    await client.list_groups()
    assert fake.count("GET", "/catalog/groups") == 1  # catalog is cached
    await client.list_groups(force=True)
    assert fake.count("GET", "/catalog/groups") == 2
    await client.get_wallet()
    await client.get_wallet()
    assert fake.count("GET", "/wallet") == 1
    client.invalidate("/wallet")
    await client.get_wallet()
    assert fake.count("GET", "/wallet") == 2


async def test_live_endpoints_are_never_cached(client, fake):
    await client.get_service_status(150)
    await client.get_service_status(150)
    await client.get_traffic(150)
    await client.get_traffic(150)
    assert fake.count("GET", "/services/status") == 2 and fake.count("GET", "/services/traffic") == 2


async def test_concurrent_identical_gets_are_coalesced(client, fake):
    results = await asyncio.gather(*[client.get_service_status(150) for _ in range(5)])
    assert len(results) == 5 and fake.count("GET", "/services/status") == 1


async def test_single_flight_propagates_errors_to_all_waiters():
    gate = asyncio.Event()

    async def run() -> list:
        c = make(lambda req: httpx.Response(404, json=err("SERVICE_NOT_FOUND")))
        return await asyncio.gather(*[c.get_service_status(9) for _ in range(3)], return_exceptions=True)

    out = await run()
    assert all(isinstance(e, TrustHostNotFoundError) for e in out)


async def test_mutations_invalidate_related_caches(client, fake):
    await client.list_invoices()
    await client.get_wallet()
    await client.pay_invoice_with_credit(8841)
    await client.list_invoices()
    await client.get_wallet()
    assert fake.count("GET", "/invoices") == 2 and fake.count("GET", "/wallet") == 2


async def test_none_params_are_not_sent(client, fake):
    await client.list_invoices(None, force=True)
    assert fake.calls[-1][2] == {}
    await client.create_order(product_id=12)
    body = fake.last_body("POST", "/orders/create")
    assert set(body) == {"product_id", "billingcycle"}  # no null noise, no empty configoptions
