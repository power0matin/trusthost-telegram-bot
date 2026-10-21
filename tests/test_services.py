from __future__ import annotations

import asyncio

import pytest

from app.core.guard import OperationInProgress
from app.services import validators
from app.services.catalog_service import cycle_prices, description_lines, normalize_cycle
from app.services.order_service import OrderDraft, build_steps
from app.services.traffic_service import DailyPoint, bucket_points, parse_daily
from app.trusthost.exceptions import (
    TrustHostAuthenticationError, TrustHostBadRequestError, TrustHostConflictError,
    TrustHostInsufficientCreditError, TrustHostNotFoundError, TrustHostUnprocessableError,
)
from app.trusthost.models import DailyTraffic, Product
from tests.conftest import ADMIN_ID
from tests.fakes import err, ok

UID = ADMIN_ID


# ------------------------------------------------------------------ orders
def draft(**kw):  # type: ignore[no-untyped-def]
    base = dict(product_id=12, product_name="VPS Germany", cycle="monthly")
    base.update(kw)
    return OrderDraft(**base)


async def test_order_payload_maps_documented_fields(app):
    d = draft(config={"1": 11, "2": 3}, custom={"5": "web"}, hostname="srv1.example.com", rootpw="S3cretPass!",
              promo="WELCOME10", gateway="usdt", domain="example.com")
    result = await app.hub.orders.create(UID, d)
    body = app.fake.last_body("POST", "/orders/create")
    assert body == {"product_id": 12, "billingcycle": "monthly", "promocode": "WELCOME10", "payment_method": "usdt",
                    "configoptions": {"1": 11, "2": 3}, "customfields": {"5": "web"}, "domain": "example.com",
                    "hostname": "srv1.example.com", "rootpw": "S3cretPass!"}
    assert result.invoice_id and result.total == 1215000 and not result.is_duplicate
    assert d.rootpw is None  # wiped from the draft object after submit


async def test_order_duplicate_is_flagged_not_recreated(app):
    first = await app.hub.orders.create(UID, draft())
    second = await app.hub.orders.create(UID, draft())
    assert second.is_duplicate and second.invoice_id == first.invoice_id
    assert len(app.fake.orders) == 1


async def test_order_double_click_creates_one_order(app):
    results = await asyncio.gather(*[app.hub.orders.create(UID, draft()) for _ in range(3)], return_exceptions=True)
    assert sum(isinstance(r, OperationInProgress) for r in results) == 2
    assert app.fake.count("POST", "/orders/create") == 1


async def test_order_rejects_invalid_hostname_before_calling_api(app):
    with pytest.raises(validators.InputError):
        await app.hub.orders.create(UID, draft(hostname="bad_host!"))
    assert app.fake.count("POST", "/orders/create") == 0


async def test_order_promo_error_is_surfaced(app):
    with pytest.raises(TrustHostBadRequestError) as ei:
        await app.hub.orders.create(UID, draft(promo="NOPE"))
    assert ei.value.code == "PROMO_NOT_FOUND"


async def test_order_audited_without_secrets(app):
    await app.hub.orders.create(UID, draft(rootpw="S3cretPass!"))
    rows = await app.repo.list_audit(UID)
    assert rows[0].action == "CREATE_ORDER" and rows[0].result == "success"
    assert "S3cretPass" not in repr(rows)


async def test_order_tracks_invoice_for_payment_notifications(app):
    r = await app.hub.orders.create(UID, draft())
    assert (await app.repo.get_states(UID, "payments"))[str(r.invoice_id)] == "Unpaid"


async def test_dynamic_steps_come_from_the_api(app):
    opts = await app.hub.catalog.options(12)
    assert build_steps(opts) == [("o", 1), ("o", 2), ("f", 5)]
    assert not opts.config_options[0].is_quantity and opts.config_options[1].is_quantity


# ------------------------------------------------------------------ renewal
async def test_renew_creates_then_reuses_invoice(app):
    first = await app.hub.servers.renew(UID, 150)
    assert first.created and first.invoice_id == 8902
    again = await app.hub.servers.renew(UID, 150)
    assert not again.created and again.invoice_id == 8902  # no duplicate charge


async def test_renew_with_promo(app):
    r = await app.hub.servers.renew(UID, 150, "WELCOME10")
    assert r.promo == {"code": "WELCOME10", "discount": 337500} and r.total == 1012500


async def test_renew_not_renewable_is_audited(app):
    with pytest.raises(TrustHostConflictError) as ei:
        await app.hub.servers.renew(UID, 151)
    assert ei.value.code == "NOT_RENEWABLE"
    rows = await app.repo.list_audit(UID)
    assert rows[0].result == "failure" and rows[0].detail == "NOT_RENEWABLE"


async def test_renew_bad_promo_issues_nothing(app):
    with pytest.raises(TrustHostUnprocessableError):
        await app.hub.servers.renew(UID, 150, "BADCODE")
    assert not any(i["id"] == 8902 for i in app.fake.invoices)


async def test_renew_unknown_service_is_404(app):
    with pytest.raises(TrustHostNotFoundError):
        await app.hub.servers.service(999)


# ------------------------------------------------------------------ traffic top-up
async def test_topup_sizes_come_from_quote_not_from_code(app):
    q = await app.hub.traffic.topup_quote(150)
    assert [o.gb for o in q.options] == [100, 500, 1000]
    app.fake.TOPUP = [(250, 100000)]  # API changed tomorrow → the bot follows
    q2 = await app.hub.traffic.topup_quote(150)
    assert [o.gb for o in q2.options] == [250]
    r = await app.hub.traffic.topup_create(UID, 150, 250)
    assert r.total == 100000


async def test_topup_with_traffic_promo_and_tier_recheck(app):
    r = await app.hub.traffic.topup_create(UID, 150, 100, "TOPUP40")
    assert r.discount == 48000 and r.total == 72000
    with pytest.raises(TrustHostBadRequestError) as ei:
        await app.hub.traffic.topup_create(UID, 150, 5000)  # not offered → blocked before any POST
    assert ei.value.code == "TRAFFIC_TIER_UNAVAILABLE" and app.fake.count("POST", "/services/traffic-topup") == 1


async def test_topup_double_click_is_guarded(app):
    out = await asyncio.gather(*[app.hub.traffic.topup_create(UID, 150, 100) for _ in range(3)], return_exceptions=True)
    assert sum(isinstance(r, OperationInProgress) for r in out) == 2 and app.fake.count("POST", "/services/traffic-topup") == 1


async def test_usage_days_validated_locally(app):
    for bad in (0, 91):
        with pytest.raises(validators.InputError):
            await app.hub.traffic.usage(150, bad)
    assert (await app.hub.traffic.usage(150, 90)).service_id == 150


# ------------------------------------------------------------------ billing
async def test_pay_preview_math(app):
    p = await app.hub.billing.pay_preview(8841)
    assert (p.balance, p.payable, p.remaining, p.sufficient, p.unpaid) == (2_000_000, 1_350_000, 650_000, True, True)


async def test_pay_with_wallet_success_updates_wallet_and_audit(app):
    r = await app.hub.billing.pay_with_wallet(UID, 8841)
    assert r.status == "Paid" and r.wallet_balance == 650_000
    assert (await app.repo.list_audit(UID))[0].action == "PAY_INVOICE"
    assert (await app.hub.billing.invoice(8841)).status == "Paid"


async def test_pay_insufficient_credit_charges_nothing(app):
    app.fake.wallet = 100
    with pytest.raises(TrustHostInsufficientCreditError):
        await app.hub.billing.pay_with_wallet(UID, 8841)
    assert app.fake.wallet == 100
    p = await app.hub.billing.pay_preview(8841)
    assert not p.sufficient and p.remaining == 100 - 1_350_000


async def test_pay_already_paid_invoice(app):
    await app.hub.billing.pay_with_wallet(UID, 8841)
    with pytest.raises(TrustHostConflictError) as ei:
        await app.hub.billing.pay_with_wallet(UID, 8841)
    assert ei.value.code == "INVOICE_NOT_UNPAID" and app.fake.wallet == 650_000


async def test_pay_double_click_spends_once(app):
    out = await asyncio.gather(*[app.hub.billing.pay_with_wallet(UID, 8841) for _ in range(4)], return_exceptions=True)
    assert sum(isinstance(r, OperationInProgress) for r in out) == 3
    assert app.fake.count("POST", "/invoices/pay-credit") == 1 and app.fake.wallet == 650_000


async def test_invoice_lookup_unknown_and_pay_url_gateways(app):
    with pytest.raises(TrustHostNotFoundError):
        await app.hub.billing.invoice(1)
    usdt = await app.hub.billing.pay_url(8841, "usdt")
    card = await app.hub.billing.pay_url(8841)
    assert usdt.gateway == "usdt" and card.gateway == "zarinpal"
    assert app.fake.calls[-2][2]["gateway"] == "usdt" and "gateway" not in app.fake.calls[-1][2]


async def test_invoice_credit_changes_payable_estimate(app):
    app.fake.invoices[0].update(credit=350000)
    assert (await app.hub.billing.invoice(8841)).payable == 1_000_000


# ------------------------------------------------------------------ power
async def test_power_off_waits_for_confirmation_from_status(app):
    sent = []

    async def on_sent(r):  # type: ignore[no-untyped-def]
        sent.append(r.action)

    out = await app.hub.servers.power_and_verify(UID, 150, "off", on_sent)
    assert sent == ["off"] and out.reached is True and out.final.power_state == "POWERED_OFF"
    assert app.fake.count("GET", "/services/status") >= 2  # polled, not assumed


async def test_power_not_confirmed_is_reported_honestly(app):
    app.fake.pending_power = None
    app.fake.overrides["POST /services/power"] = (200, ok(service_id=150, action="off", message="queued"))
    out = await app.hub.servers.power_and_verify(UID, 150, "off")  # state never changes
    assert out.reached is False and out.final.power_state == "POWERED_ON"


async def test_power_poll_survives_busy_conflicts(app):
    state = {"n": 0}

    def status(_):  # type: ignore[no-untyped-def]
        state["n"] += 1
        if state["n"] == 1:
            return 409, err("BUSY")
        return 200, ok(service_id=150, service_status="Active", power_state="POWERED_OFF", cpu=4, ram_mb=1, disk_gb=1, ip="x")

    app.fake.overrides["GET /services/status"] = status
    out = await app.hub.servers.power_and_verify(UID, 150, "shutdown")
    assert out.reached is True


async def test_reboot_is_never_claimed_verified(app):
    out = await app.hub.servers.power_and_verify(UID, 150, "reboot")
    assert out.reached is None


async def test_power_on_suspended_service_is_rejected(app):
    with pytest.raises(TrustHostConflictError) as ei:
        await app.hub.servers.power_and_verify(UID, 151, "on")
    assert ei.value.code == "SERVICE_NOT_ACTIVE" and ei.value.payload["service_status"] == "Suspended"


async def test_power_double_click_sends_one_command(app):
    out = await asyncio.gather(*[app.hub.servers.power_and_verify(UID, 150, "reboot") for _ in range(3)],
                               return_exceptions=True)
    assert sum(isinstance(r, OperationInProgress) for r in out) == 2
    assert app.fake.count("POST", "/services/power") == 1


async def test_invalid_power_action_never_reaches_api(app):
    with pytest.raises(validators.InputError):
        await app.hub.servers.power_and_verify(UID, 150, "format-disk")
    assert app.fake.count("POST", "/services/power") == 0


# ------------------------------------------------------------------ tickets
async def test_ticket_create_validates_and_posts(app):
    r = await app.hub.tickets.create(UID, dept_id=2, subject="  Need   help ", message="Hello", priority="High", service_id=150)
    body = app.fake.last_body("POST", "/tickets/create")
    assert body == {"subject": "Need help", "message": "Hello", "dept_id": 2, "priority": "High", "service_id": 150}
    assert r.ticket_id == 62
    # own ticket must not trigger a "new reply" notification later
    assert str(r.ticket_id) in await app.repo.get_states(UID, "tickets")


@pytest.mark.parametrize("subject,message,priority", [("", "m", "Low"), ("s", " ", "Low"), ("s", "m", "Urgent"), ("x" * 201, "m", "Low")])
async def test_ticket_create_rejects_bad_input(app, subject, message, priority):
    with pytest.raises(validators.InputError):
        await app.hub.tickets.create(UID, dept_id=2, subject=subject, message=message, priority=priority)
    assert app.fake.count("POST", "/tickets/create") == 0


async def test_ticket_reply_and_detail(app):
    await app.hub.tickets.reply(UID, 61, "Thanks!")
    d = await app.hub.tickets.detail(61)
    assert d.replies[-1].message == "Thanks!" and not d.replies[-1].is_staff and d.replies[0].is_staff
    with pytest.raises(TrustHostNotFoundError) as ei:  # documented as HTTP 400 + TICKET_NOT_FOUND
        await app.hub.tickets.reply(UID, 5, "x")
    assert ei.value.status == 400 and ei.value.code == "TICKET_NOT_FOUND"


# ------------------------------------------------------------------ catalog parsing & helpers
def test_cycle_prices_defensive_parsing():
    p = lambda pricing: Product(id=1, name="x", pricing=pricing)  # noqa: E731
    assert cycle_prices(p({"monthly": "1350000 IRT", "annually": 5, "weird": "x"})) == {"monthly": "1350000 IRT", "annually": "5"}
    assert cycle_prices(p({"Monthly": {"price": "10"}, "Semi-Annually": {"amount": 20}})) == {"monthly": "10", "semiannually": "20"}
    assert cycle_prices(p([{"billingcycle": "Quarterly", "price": "7"}])) == {"quarterly": "7"}
    assert cycle_prices(p({})) == {} and cycle_prices(p(None)) == {} and cycle_prices(p("garbage")) == {}


async def test_cycles_fall_back_to_documented_four(app):
    prod = Product(id=1, name="x", paytype="recurring", pricing={})
    assert app.hub.catalog.cycles_for(prod) == ["monthly", "quarterly", "semiannually", "annually"]
    assert app.hub.catalog.cycles_for(Product(id=2, name="y", paytype="onetime")) == ["monthly"]
    assert app.hub.catalog.cycles_for(Product(id=3, name="z", paytype="recurring", pricing={"quarterly": "1"})) == ["quarterly"]
    assert normalize_cycle("Semi-Annually") == "semiannually" and normalize_cycle("???") is None


def test_description_lines_strips_html():
    p = Product(id=1, name="x", description=["<b>4 vCPU</b>", "", "8 GB"])
    assert description_lines(p) == ["4 vCPU", "8 GB"]


def test_daily_parse_and_bucket():
    d = DailyTraffic.model_validate({"unit": "GiB", "from": "2026-09-01", "to": "2026-09-30", "items": [
        {"date": "2026-09-02", "inbound_gb": 2, "outbound_gb": 1}, {"date": "2026-09-01", "inbound_gb": 1}, {"nonsense": True}]})
    pts = parse_daily(d)
    assert [p.label for p in pts] == ["2026-09-01", "2026-09-02"] and pts[0].outbound == 0
    many = [DailyPoint(f"2026-09-{i:02d}", 1.0, 0.0) for i in range(1, 31)]
    b = bucket_points(many, 15)
    assert len(b) <= 15 and sum(p.inbound for p in b) == 30
    assert parse_daily(None) == []


def test_validators():
    assert validators.hostname("SRV1.Example.com.") == "srv1.example.com"
    for bad in ("", "-a.com", "a..com", "a_b.com", "x" * 64 + ".com"):
        with pytest.raises(validators.InputError):
            validators.hostname(bad)
    assert validators.domain("example.com") == "example.com"
    with pytest.raises(validators.InputError):
        validators.domain("localhost")
    assert validators.promo_code(" WELCOME10 ") == "WELCOME10"
    for bad in ("", "a b", "x" * 51, "$$"):
        with pytest.raises(validators.InputError):
            validators.promo_code(bad)
    assert validators.quantity("4") == 4
    for bad in ("-1", "1.5", "abc", ""):
        with pytest.raises(validators.InputError):
            validators.quantity(bad)
    assert validators.root_password("S3cretPass!") == "S3cretPass!"
    for bad in ("short", " leadingspace1", "x" * 129):
        with pytest.raises(validators.InputError):
            validators.root_password(bad)


# ------------------------------------------------------------------ dashboard
async def test_dashboard_counts_and_graceful_partial_failure(app):
    d = await app.hub.account.dashboard(force=True)
    assert (d.balance, d.total, d.active, d.suspended, d.unpaid, d.partial) == (2_000_000, 2, 1, 1, 1, False)
    app.fake.overrides["GET /invoices"] = (500, err("SERVER_ERROR"))
    app.hub.client.invalidate("/invoices")
    d2 = await app.hub.account.dashboard(force=True)
    assert d2.partial and d2.unpaid is None and d2.balance == 2_000_000


async def test_dashboard_auth_failure_is_raised_not_hidden(app):
    for route in ("/wallet", "/services", "/invoices"):
        app.fake.overrides[f"GET {route}"] = (401, err("UNAUTHORIZED"))
    with pytest.raises(TrustHostAuthenticationError):
        await app.hub.account.dashboard(force=True)
