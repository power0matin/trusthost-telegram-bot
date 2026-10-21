"""Contract tests for TrustHost Customer API 1.3.3 (changes since 1.1.0). No network: MockTransport only."""
from __future__ import annotations

import base64
import json
import logging

import httpx
import pytest

from app.bot.callbacks import Menu, Tkt, Wal
from app.core.config import Settings
from app.i18n.errors import translate_exception, translate_trusthost_error
from app.services import validators
from app.trusthost.exceptions import (
    TrustHostAPIError, TrustHostConflictError, TrustHostInsufficientCreditError, TrustHostProtocolError,
    TrustHostServerError,
)
from app.trusthost.client import TrustHostClient
from tests.fakes import API_KEY, API_SECRET, err, ok

BASE = "https://my.trusthost.co/api/v1"
UID = 111


def make(handler, **kw):  # type: ignore[no-untyped-def]
    async def sleep(_: float) -> None:
        return None

    return TrustHostClient(BASE, API_KEY, API_SECRET, transport=httpx.MockTransport(handler), sleep=sleep,
                           max_requests_per_minute=1000, **kw)


def recorder(payload, status=200, headers=None):  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json=payload, headers=headers or {})

    return handler, seen


# ------------------------------------------------------------------ base URL / config
def test_default_base_url_is_the_documented_co_host():
    s = Settings(_env_file=None, trusthost_api_key=API_KEY, trusthost_api_secret=API_SECRET,
                 telegram_bot_token="123456789:AAEhBOweik6ad9r_QXMENQjcrGbqCr4K-RQ", admin_telegram_ids="1")
    assert s.trusthost_base_url == "https://my.trusthost.co/api/v1"   # no invented /v1.3.3 segment


async def test_former_ir_base_url_keeps_working():
    h, seen = recorder(ok(balance=5, add_funds_url=None))
    c = TrustHostClient("https://my.trusthost.ir/api/v1/", API_KEY, API_SECRET, transport=httpx.MockTransport(h))
    await c.get_wallet()
    assert str(seen[0].url) == "https://my.trusthost.ir/api/v1/wallet"
    await c.aclose()


# ------------------------------------------------------------------ classification filters + new fields
async def test_catalog_and_services_filters_are_sent_as_query_parameters():
    h, seen = recorder(ok(groups=[], products=[], services=[]))
    c = make(h)
    await c.list_groups(category="vps", location="iran", country="nl", city=None)
    await c.list_products(category="vps", location="iran", plan_type="game", billing="hourly", cpu_type="shared")
    await c.list_services(status="Active", category="hosting", city="moscow")
    q = [dict(r.url.params) for r in seen]
    assert q[0] == {"category": "vps", "location": "iran", "country": "nl"}
    assert q[1] == {"category": "vps", "location": "iran", "plan_type": "game", "billing": "hourly",
                    "cpu_type": "shared"}
    assert q[2] == {"status": "Active", "category": "hosting", "city": "moscow"}
    with pytest.raises(TypeError):
        await c.list_groups(colour="red")


async def test_unknown_filter_value_400_is_typed_and_translated():
    h, _ = recorder(err("INVALID_PLAN_TYPE", "نامعتبر"), status=400)
    c = make(h)
    with pytest.raises(TrustHostAPIError) as ei:
        await c.list_products(plan_type="nope")
    assert ei.value.code == "INVALID_PLAN_TYPE" and ei.value.status == 400
    assert "unsupported filter" in translate_exception(ei.value, "en")
    assert "INVALID_PLAN_TYPE" not in translate_exception(ei.value, "en")


async def test_models_parse_new_classification_fields_and_tolerate_nulls():
    payload = ok(groups=[{"id": 3, "name": "VS", "slug": "vs", "category": "vps", "location": "iran",
                          "plan_type": None, "billing": "recurring", "country": "ir", "city": None, "cpu_type": None,
                          "categories": ["vps"], "plan_types": None, "cpu_types": ["shared", "dedicated"],
                          "product_count": 6}],
                 products=[{"id": 12, "group_id": 3, "name": "P", "category": "vps", "billing": "hourly",
                            "in_stock": False, "stock": 0, "module": "vcenter",
                            "hourly": {"min_wallet_to_order": 1000}, "setup_fees": {}, "cycles": []}])
    h, _ = recorder(payload)
    c = make(h)
    g = (await c.list_groups())[0]
    assert g.category == "vps" and g.plan_type is None and g.plan_types == [] and g.product_count == 6
    p = (await c.list_products()).products[0]
    assert p.is_hourly and p.out_of_stock and p.hourly == {"min_wallet_to_order": 1000}


async def test_hourly_products_are_not_offered_by_the_bot(app):
    app.fake.products.append({"id": 13, "group_id": 3, "group_name": "Virtual Servers", "name": "Hourly VPS",
                              "type": "vcenter", "paytype": "recurring", "billing": "hourly",
                              "pricing": {"monthly": "1 IRT"}})
    names = [p.name for p in await app.hub.catalog.products()]
    assert names == ["VPS Germany"]
    from app.trusthost.exceptions import TrustHostNotFoundError
    with pytest.raises(TrustHostNotFoundError):
        await app.hub.catalog.product(13)


# ------------------------------------------------------------------ orders
@pytest.mark.parametrize("cycle", ["monthly", "biennially", "triennially", "hourly"])
async def test_order_accepts_documented_cycles(cycle):
    h, seen = recorder(ok(order_id=1, invoice_id=2, total=0, status="Paid"))
    c = make(h)
    await c.create_order(product_id=12, billingcycle=cycle, payment_method="usdt")
    body = json.loads(seen[0].content)
    assert body["billingcycle"] == cycle and body["payment_method"] == "usdt"
    await c.aclose()


async def test_order_rejects_undocumented_cycle_or_gateway_before_any_request():
    h, seen = recorder(ok())
    c = make(h)
    with pytest.raises(ValueError):
        await c.create_order(product_id=12, billingcycle="weekly")
    with pytest.raises(ValueError):
        await c.create_order(product_id=12, payment_method="paypal")
    assert seen == []


@pytest.mark.parametrize(("status", "code", "cls", "needle"), [
    (402, "INSUFFICIENT_CREDIT", TrustHostInsufficientCreditError, "balance is not enough"),
    (409, "OUT_OF_STOCK", TrustHostConflictError, "out of stock"),
    (400, "INVALID_BILLING_CYCLE", TrustHostAPIError, "billing cycle is not available"),
])
async def test_order_errors_for_hourly_and_stock(status, code, cls, needle):
    h, seen = recorder(err(code), status=status)
    c = make(h)
    with pytest.raises(cls) as ei:
        await c.create_order(product_id=12, billingcycle="hourly")
    assert ei.value.code == code and needle in translate_exception(ei.value, "en")
    assert len(seen) == 1                      # state-changing POST is never retried


async def test_duplicate_order_flag_is_parsed():
    h, _ = recorder(ok(order_id=5, invoice_id=8, total=1, status="Unpaid", is_duplicate=True))
    r = await make(h).create_order(product_id=12)
    assert r.is_duplicate is True


# ------------------------------------------------------------------ invoices: pagination + details
async def test_invoice_pagination_parameters_and_object():
    h, seen = recorder(ok(invoices=[{"id": 1, "total": 5, "status": "Paid"}],
                          pagination={"page": 2, "limit": 50, "total": 120, "has_more": True}))
    c = make(h)
    page = await c.list_invoices_page("Paid", page=2, limit=50)
    assert dict(seen[0].url.params) == {"status": "Paid", "page": "2", "limit": "50"}
    assert page.pagination.has_more and page.pagination.total == 120 and page.invoices[0].id == 1
    for bad in (dict(limit=0), dict(limit=101), dict(page=0)):
        with pytest.raises(ValueError):
            await c.list_invoices_page(**bad)
    assert len(seen) == 1


async def test_invoice_page_without_pagination_object_is_tolerated():
    h, _ = recorder(ok(invoices=[]))
    page = await make(h).list_invoices_page()
    assert page.pagination.has_more is False and page.invoices == []


async def test_invoice_details_route_and_model(client, fake):
    inv = await client.get_invoice(8841)
    assert (inv.id, inv.status, inv.balance, inv.is_unpaid) == (8841, "Unpaid", 1350000, True)
    assert inv.items and inv.payments == []
    assert fake.last_body("GET", "/invoices/details") == {"invoice_id": "8841"}


async def test_invoice_details_404_and_malformed_body(client, fake):
    with pytest.raises(TrustHostAPIError) as ei:
        await client.get_invoice(1)
    assert ei.value.code == "INVOICE_NOT_FOUND" and ei.value.status == 404
    fake.overrides["GET /invoices/details"] = (200, ok())
    with pytest.raises(TrustHostProtocolError):
        await client.get_invoice(8841)


async def test_billing_service_uses_single_invoice_endpoint(app):
    inv = await app.hub.billing.invoice(8800)
    assert inv.status == "Paid"
    assert app.fake.count("GET", "/invoices/details") == 1 and app.fake.count("GET", "/invoices") == 0


async def test_pay_url_new_fields_and_already_paid(client, fake):
    fake.overrides["GET /invoices/pay-url"] = (200, ok(invoice_id=8841, gateway="zarinpal", gateway_title="زرین‌پال",
                                                        direct_payment_url="https://x/y", amount=5, authority="A1"))
    link = await client.get_pay_url(8841)
    assert link.gateway_title and link.authority == "A1"
    with pytest.raises(ValueError):
        await client.get_pay_url(8841, "bitcoin")


# ------------------------------------------------------------------ wallet top-up
async def test_wallet_topup_request_and_response(client, fake):
    r = await client.topup_wallet(500_000, "usdt")
    assert fake.last_body("POST", "/wallet/topup") == {"amount": 500000, "gateway": "usdt"}
    assert r.invoice_id and r.amount == 500000 and r.best_url.endswith(f"/usdt/{r.invoice_id}")
    r2 = await client.topup_wallet(20_000)
    assert "gateway" not in fake.last_body("POST", "/wallet/topup") and r2.payment_method == "zarinpal"


async def test_wallet_topup_minimum_is_success_false_with_http_200(client):
    with pytest.raises(TrustHostAPIError) as ei:
        await client.topup_wallet(9_999)
    assert ei.value.code == "MINIMUM_AMOUNT" and ei.value.status == 200


async def test_wallet_topup_service_validates_audits_and_tracks(app):
    with pytest.raises(validators.InputError):
        await app.hub.billing.topup(UID, 5_000)
    assert app.fake.count("POST", "/wallet/topup") == 0
    r = await app.hub.billing.topup(UID, 100_000)
    rows = await app.repo.list_audit(UID)
    assert rows[0].action == "WALLET_TOPUP" and rows[0].result == "success"
    assert str(r.invoice_id) in (await app.repo.get_states(UID, "payments"))


async def test_wallet_topup_is_never_retried_after_a_server_error():
    h, seen = recorder(err("SERVER_ERROR"), status=500)
    c = make(h)
    with pytest.raises(TrustHostServerError):
        await c.topup_wallet(50_000)
    assert len(seen) == 1


@pytest.mark.parametrize(("raw", "expected"), [("500000", 500000), ("500,000", 500000), ("۵۰۰۰۰۰", 500000),
                                                (" 10 000 ", 10000)])
def test_wallet_amount_parsing(raw, expected):
    assert validators.wallet_amount(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "9999", "-50000", "12.5", "99999999999", "²²²²²²"])
def test_wallet_amount_rejects_bad_input(raw):
    with pytest.raises(validators.InputError):
        validators.wallet_amount(raw)


async def test_wallet_topup_telegram_flow_creates_exactly_one_invoice(en):
    await en.tg.click(Menu(a="wal"))
    await en.tg.press("Top up wallet")
    await en.tg.send("abc")
    assert "Invalid amount" in en.tg.last_text() and en.fake.count("POST", "/wallet/topup") == 0
    await en.tg.send("250,000")
    assert "250,000 Toman" in en.tg.last_text() and en.fake.count("POST", "/wallet/topup") == 0
    await en.tg.click(Wal(a="go", g="u"))
    assert "Top-up invoice issued" in en.tg.last_text()
    assert en.fake.last_body("POST", "/wallet/topup") == {"amount": 250000, "gateway": "usdt"}
    assert en.tg.find_button("Open").url.startswith("https://pay.example/usdt/")
    await en.tg.click(Wal(a="go"))                      # replayed button: nothing more is created
    assert en.fake.count("POST", "/wallet/topup") == 1 and "expired" in en.tg.last_text()


async def test_wallet_topup_telegram_flow_persian(fa):
    await fa.tg.click(Menu(a="wal"))
    await fa.tg.click(Wal(a="t"))
    await fa.tg.send("۵۰۰۰۰۰")
    await fa.tg.click(Wal(a="go"))
    assert "فاکتور شارژ صادر شد" in fa.tg.last_text()
    assert fa.fake.last_body("POST", "/wallet/topup") == {"amount": 500000}


async def test_wallet_topup_api_error_is_shown_not_swallowed(en):
    en.fake.overrides["POST /wallet/topup"] = (200, err("MINIMUM_AMOUNT"))
    await en.tg.click(Wal(a="t"))
    await en.tg.send("50000")
    await en.tg.click(Wal(a="go"))
    assert "below the minimum" in en.tg.last_text()


# ------------------------------------------------------------------ services: details / credentials / cancel
async def test_service_details_model(client, fake):
    d = await client.get_service(150)
    assert d.id == 150 and d.category == "vps" and d.display_ip == "203.0.113.10" and d.can_power
    assert d.traffic == {"window_days": 30} and d.power_state == "POWERED_ON"


async def test_service_not_found_is_success_false_with_http_200(client):
    with pytest.raises(TrustHostAPIError) as ei:
        await client.get_service(999)
    assert ei.value.code == "SERVICE_NOT_FOUND"


async def test_credentials_are_never_cached_logged_or_printed(client, fake, caplog):
    caplog.set_level(logging.DEBUG)
    creds = await client.get_credentials(150)
    await client.get_credentials(150)
    assert fake.count("GET", "/services/credentials") == 2        # not cached
    assert creds.password == "S3cr3t-Pa55-from-api" and creds.port == 22
    assert "S3cr3t" not in repr(creds) and "S3cr3t" not in str(creds)
    assert "S3cr3t" not in caplog.text
    from app.core.security import redact_text
    assert "S3cr3t-Pa55-from-api" not in redact_text("oops S3cr3t-Pa55-from-api leaked")


async def test_cancel_request_body_and_validation(client, fake):
    r = await client.cancel_service(150, "Immediate", "moving")
    assert fake.last_body("POST", "/services/cancel") == {"service_id": 150, "type": "Immediate", "reason": "moving"}
    assert r.already_exists is False
    await client.cancel_service(150)
    assert fake.last_body("POST", "/services/cancel")["type"] == "End of Billing Period"
    with pytest.raises(ValueError):
        await client.cancel_service(150, "whenever")


async def test_cancel_already_cancelled_is_translated(client, fake):
    fake.overrides["POST /services/cancel"] = (200, err("ALREADY_CANCELLED"))
    with pytest.raises(TrustHostAPIError) as ei:
        await client.cancel_service(150)
    assert "already exists" in translate_exception(ei.value, "en")


# ------------------------------------------------------------------ renewal (response shape changed)
async def test_renew_new_shape_and_is_existing_semantics(client, fake):
    r = await client.renew_service(150, "WELCOME10", gateway="usdt")
    assert fake.last_body("POST", "/services/renew") == {"service_id": 150, "promocode": "WELCOME10",
                                                           "gateway": "usdt"}
    assert r.is_existing is False and r.created is True and r.status == "Unpaid" and r.product_name
    r2 = await client.renew_service(150)
    assert r2.is_existing is True and r2.created is False


async def test_renew_legacy_created_flag_is_still_understood():
    from app.trusthost.models import RenewResult
    assert RenewResult.model_validate({"invoice_id": 1, "created": False}).is_existing is True
    assert RenewResult.model_validate({"invoice_id": 1, "created": True}).created is True


@pytest.mark.parametrize(("status", "code"), [(409, "PROMO_ALREADY_APPLIED"), (409, "INVOICE_NOT_UNPAID"),
                                               (409, "SERVICE_NOT_ACTIVE"), (422, "PROMO_NOT_APPLICABLE"),
                                               (422, "PROMO_TRAFFIC_ONLY")])
async def test_renew_documented_failures_are_translated(status, code):
    h, _ = recorder(err(code, service_status="Terminated"), status=status)
    with pytest.raises(TrustHostAPIError) as ei:
        await make(h).renew_service(150, "X")
    text = translate_exception(ei.value, "en")
    assert code not in text and "(code:" not in text


async def test_renewal_screen_shows_paid_when_promo_covers_everything(en):
    en.fake.overrides["POST /services/renew"] = (200, ok(service_id=150, invoice_id=8999, total=0, is_existing=False,
                                                         status="Paid", promo={"code": "FREE", "discount": 1350000}))
    await en.tg.click("rn:go:150")
    t = en.tg.last_text()
    assert "#8999" in t and "Paid" in t and "FREE" in t


# ------------------------------------------------------------------ power: 502 ACTION_FAILED
async def test_power_502_action_failed_is_typed_translated_and_not_retried():
    h, seen = recorder(err("ACTION_FAILED"), status=502)
    with pytest.raises(TrustHostServerError) as ei:
        await make(h).power_service(150, "reboot")
    assert ei.value.code == "ACTION_FAILED" and len(seen) == 1
    assert "did not accept" in translate_exception(ei.value, "en")
    assert "نپذیرفت" in translate_exception(ei.value, "fa")


# ------------------------------------------------------------------ rate limiting
async def test_429_with_retry_after_blocks_followups_and_is_not_retried():
    h, seen = recorder(err("RATE_LIMITED"), status=429, headers={"Retry-After": "60"})
    c = make(h)
    from app.trusthost.exceptions import TrustHostRateLimitError
    with pytest.raises(TrustHostRateLimitError) as ei:
        await c.create_order(product_id=12)
    assert ei.value.retry_after == 60
    with pytest.raises(TrustHostRateLimitError) as ei2:
        await c.get_wallet()
    assert ei2.value.local and len(seen) == 1
    assert "60 seconds" in translate_exception(ei.value, "en")


# ------------------------------------------------------------------ tickets
async def test_ticket_close_route_and_cache_invalidation(client, fake):
    await client.list_tickets()
    await client.close_ticket(61)
    assert fake.last_body("POST", "/tickets/close") == {"ticket_id": 61}
    assert (await client.list_tickets())[0].status == "Closed"     # list cache was dropped


async def test_ticket_close_not_found_is_success_false(client):
    with pytest.raises(TrustHostAPIError) as ei:
        await client.close_ticket(404)
    assert ei.value.code == "TICKET_NOT_FOUND"


async def test_ticket_attachment_is_sent_inline_base64_and_bounded(client, fake):
    await client.reply_ticket(61, "see file", attachment=("log.txt", b"hello"))
    body = fake.last_body("POST", "/tickets/reply")
    assert body["attachment"] == {"name": "log.txt", "content_b64": base64.b64encode(b"hello").decode()}
    await client.reply_ticket(61, "no file")
    assert "attachment" not in fake.last_body("POST", "/tickets/reply")
    with pytest.raises(ValueError):
        await client.reply_ticket(61, "x", attachment=("big.zip", b"0" * 1_000_001))
    with pytest.raises(ValueError):
        await client.create_ticket("s", "m", attachment=("", b"x"))


async def test_ticket_close_telegram_flow_requires_confirmation(en):
    await en.tg.click(Tkt(a="d", id=61))
    await en.tg.click(Tkt(a="cx", id=61))
    assert "Close ticket #482913?" in en.tg.last_text() and en.fake.count("POST", "/tickets/close") == 0
    await en.tg.click(Tkt(a="cc", id=61))
    assert "closed" in en.tg.last_text() and en.fake.count("POST", "/tickets/close") == 1
    await en.tg.click(Tkt(a="d", id=61))
    assert not any("Close ticket" in b.text for b in en.tg.buttons())   # no close button on a closed ticket


# ------------------------------------------------------------------ envelope rules
async def test_missing_success_flag_and_non_json_are_protocol_errors():
    c = make(lambda r: httpx.Response(200, json={"balance": 1}))
    with pytest.raises(TrustHostProtocolError):
        await c.get_wallet()
    c2 = make(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(TrustHostProtocolError):
        await c2.get_wallet()


@pytest.mark.parametrize(("status", "code"), [(401, "UNAUTHORIZED"), (403, "API_DISABLED"), (403, "FORBIDDEN"),
                                               (405, "METHOD_NOT_ALLOWED")])
async def test_documented_auth_and_method_errors_are_translated(status, code):
    h, _ = recorder(err(code), status=status)
    with pytest.raises(TrustHostAPIError) as ei:
        await make(h).get_wallet()
    assert "(code:" not in translate_exception(ei.value, "en")


def test_every_new_error_code_is_translated_in_both_languages():
    for code in ("ACTION_FAILED", "INVALID_BILLING_CYCLE", "MINIMUM_AMOUNT", "ALREADY_CANCELLED", "OUT_OF_STOCK",
                 "PROMO_TRAFFIC_ONLY", "PROMO_NOT_APPLICABLE", "API_DISABLED", "INVALID_CATEGORY"):
        for lang in ("en", "fa"):
            assert "(code:" not in translate_trusthost_error(code, lang), (code, lang)
