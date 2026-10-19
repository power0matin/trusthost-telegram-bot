from __future__ import annotations

import asyncio
import re

from aiogram.fsm.storage.base import StorageKey

from app.i18n import CATALOGS
from app.bot.callbacks import Cat, Inv, Menu, Nav, Pow, Srv, Top, Tkt, Use
from tests.conftest import ADMIN_ID
from tests.fakes import err, ok


async def state_data(app) -> dict:  # type: ignore[no-untyped-def]
    key = StorageKey(bot_id=app.bot.id, chat_id=ADMIN_ID, user_id=ADMIN_ID)
    return await app.dp.storage.get_data(key)


# ====================================================================== authorization
async def test_unauthorized_user_is_blocked_with_localized_message_and_no_side_effects(app):
    await app.tg.send("/start", uid=999)
    assert app.tg.last_text() == "⛔ You are not authorized to use this bot."
    app.tg.lang_code = "fa"
    await app.tg.send("/servers", uid=999)
    assert app.tg.last_text() == "⛔ دسترسی شما به این ربات مجاز نیست."
    await app.tg.click(Menu(a="srv"), uid=999)
    assert app.fake.calls == []                       # TrustHost never touched, config not probed
    assert await app.repo.list_users() == []          # no DB row for strangers
    answer = [r for r in app.session.requests if type(r).__name__ == "AnswerCallbackQuery"][-1]
    assert answer.show_alert is True and "مجاز نیست" in answer.text


async def test_unauthorized_never_reveals_api_health(app):
    app.fake.overrides["GET /wallet"] = (401, err("UNAUTHORIZED"))
    await app.tg.send("/health", uid=999)
    assert "TrustHost" not in app.tg.last_text() and "API" not in app.tg.last_text()


# ====================================================================== language
async def test_start_asks_for_language_then_persists_it(app):
    await app.tg.send("/start")
    first = app.tg.last()
    assert "Please choose your language" in first.text
    assert [b.text for b in app.tg.buttons(first)] == ["🇮🇷 فارسی", "🇬🇧 English"]
    assert app.fake.calls == []   # nothing loaded before a language exists

    await app.tg.click("lg:fa:s")
    assert "پنل مدیریت TrustHost" in app.tg.last_text()
    assert "۲٬۰۰۰٬۰۰۰ تومان" in app.tg.last_text()          # Persian digits + separator
    assert (await app.repo.get_or_create_user(ADMIN_ID)).language == "fa"

    app.tg.reset()
    await app.tg.send("/start")                             # preference survives: no prompt again
    assert "Please choose" not in app.tg.all_text() and "پنل مدیریت" in app.tg.last_text()


async def test_switching_language_in_settings_changes_whole_ui(en):
    await en.tg.send("/settings")
    assert "Settings" in en.tg.last_text()
    await en.tg.press("Language")
    await en.tg.click("lg:fa:t")
    assert en.tg.last_text() == "⚙️ <b>تنظیمات</b>"
    assert any("زبان" in b.text for b in en.tg.buttons())
    assert (await en.repo.get_or_create_user(ADMIN_ID)).language == "fa"


async def test_dashboard_en_is_complete_and_uses_real_data(en):
    await en.tg.send("/start")
    t = en.tg.last_text()
    for needle in ("Management Panel", "2,000,000 Toman", "Services: <b>2</b>", "Active: 1", "Suspended: 1", "Unpaid invoices: <b>1</b>", "Last updated"):
        assert needle in t, needle
    labels = [b.text for b in en.tg.buttons()]
    assert "🖥 My Servers" in labels and "🛒 Order Service" in labels and "⚙️ Settings" in labels
    assert en.fake.count("GET", "/wallet") == 1 and en.fake.count("GET", "/services") == 1  # 3 requests total


async def test_dashboard_degrades_but_menu_still_works_when_api_down(en):
    for route in ("/wallet", "/services", "/invoices"):
        en.fake.overrides[f"GET {route}"] = (500, err("SERVER_ERROR"))
    await en.tg.send("/start")
    assert "temporary error" in en.tg.last_text() and "Traceback" not in en.tg.last_text()
    assert any("My Servers" in b.text for b in en.tg.buttons())      # user is never stuck


# ====================================================================== servers
async def test_servers_list_detail_and_navigation(en):
    await en.tg.click(Menu(a="srv"))
    assert "VPS Germany" in en.tg.last_text() and "203.0.113.10" in en.tg.last_text()
    await en.tg.press("VPS Germany")
    d = en.tg.last_text()
    for needle in ("VPS Germany", "ID: <code>150</code>", "203.0.113.10", "Active", "Monthly", "1,350,000 Toman", "2026-10-21"):
        assert needle in d, needle
    labels = [b.text for b in en.tg.buttons()]
    for want in ("Status", "Usage", "Traffic", "Power", "Renew", "Top-up", "Support", "Back", "Home"):
        assert any(want in l for l in labels), want
    await en.tg.press("Back")
    assert "My Servers" in en.tg.last_text()
    await en.tg.press("Home")
    assert "Management Panel" in en.tg.last_text()


async def test_live_status_translates_power_state(en):
    await en.tg.click(Srv(a="st", id=150))
    t = en.tg.last_text()
    assert "Powered on" in t and "4 vCPU" in t and "8 GB" in t and "120 GB" in t and "203.0.113.10" in t
    en.fake.power_state = "POWERED_OFF"
    await en.tg.press("Refresh")
    assert "Powered off" in en.tg.last_text()


async def test_forged_service_id_is_rejected_without_leaking(en):
    await en.tg.click(Srv(a="d", id=424242))
    assert "not found in your account" in en.tg.last_text()
    assert any("Home" in b.text for b in en.tg.buttons())


async def test_power_off_requires_confirmation_and_verifies_state(en):
    await en.tg.click(Srv(a="pw", id=150))
    await en.tg.press("Power off")
    assert "Warning" in en.tg.last_text() and "Unsaved data may be lost" in en.tg.last_text()
    assert en.fake.count("POST", "/services/power") == 0           # nothing sent before confirmation
    await en.tg.press("Cancel")
    assert "Power management" in en.tg.last_text() and en.fake.count("POST", "/services/power") == 0

    await en.tg.press("Power off")
    before = len(en.tg.sent())
    await en.tg.press("Yes, power off")
    texts = [r.text for r in en.tg.sent()[before:]]
    assert any("command was sent" in t and "Checking" in t for t in texts)    # never claims success up front
    assert "confirmed" in en.tg.last_text() and "Powered off" in en.tg.last_text()
    assert en.fake.last_body("POST", "/services/power") == {"service_id": 150, "action": "off"}


async def test_power_on_needs_no_confirmation(en):
    en.fake.power_state = "POWERED_OFF"
    await en.tg.click(Pow(a="ask", id=150, act="on"))
    assert en.fake.count("POST", "/services/power") == 1 and "Powered on" in en.tg.last_text()


async def test_power_double_click_sends_single_command(en):
    data = Pow(a="do", id=150, act="reboot")
    await asyncio.gather(en.tg.click(data), en.tg.click(data), en.tg.click(data))
    assert en.fake.count("POST", "/services/power") == 1


async def test_power_conflict_is_friendly(en):
    en.fake.overrides["POST /services/power"] = (409, err("BUSY"))
    await en.tg.click(Pow(a="do", id=150, act="on"))
    t = en.tg.last_text()
    assert "busy processing another request" in t and "409" not in t and "{" not in t
    assert [b.text for b in en.tg.buttons()][-2:] == ["⬅️ Back", "🏠 Home"]


async def test_suspended_service_cannot_be_powered(en):
    await en.tg.click(Pow(a="do", id=151, act="on"))
    assert "not active (status: Suspended)" in en.tg.last_text()


# ====================================================================== traffic & usage
async def test_traffic_screen(en):
    await en.tg.click(Srv(a="tr", id=150))
    t = en.tg.last_text()
    for needle in ("412.37 / 1,000 GiB", "587.63 GiB", "41.2%", "Download: 412.37 GiB", "Upload: 58.2 GiB", "2026-09-21", "Only inbound"):
        assert needle in t, needle


async def test_usage_range_selection_only_requests_when_chosen(en):
    await en.tg.click(Srv(a="us", id=150))
    assert en.fake.last_body("GET", "/services/usage")["days"] == "30"
    t = en.tg.last_text()
    assert "last 30 days" in t and "CPU: 4 vCPU" in t and "<pre>" in t and "█" in t
    labels = [b.text for b in en.tg.buttons()]
    assert "✓ 30 Days" in labels and all(f"{n} Days" in " ".join(labels) for n in (7, 14, 60, 90))
    await en.tg.click(Use(id=150, d=7))
    assert en.fake.last_body("GET", "/services/usage")["days"] == "7" and "last 7 days" in en.tg.last_text()


async def test_usage_picker_from_main_menu(en):
    await en.tg.click(Menu(a="usage"))
    assert "choose a server" in en.tg.last_text()
    await en.tg.press("VPS Germany")
    assert "last 30 days" in en.tg.last_text()


async def test_usage_when_resources_unavailable(en):
    def usage(_):  # type: ignore[no-untyped-def]
        return 200, ok(service_id=150, service_status="Active", resources={"available": False},
                       traffic={"unit": "GiB", "inbound_gb": 1, "outbound_gb": 2, "limit_gb": None, "unlimited": True},
                       daily_traffic={"unit": "GiB", "items": [{"weird": 1}]})
    en.fake.overrides["GET /services/usage"] = usage
    await en.tg.click(Srv(a="us", id=150))
    assert "not available right now" in en.tg.last_text() and "Unlimited" in en.tg.last_text()
    assert "does not recognise" in en.tg.last_text()


# ====================================================================== top-up
async def test_topup_flow_with_dynamic_sizes_promo_and_invoice(en):
    await en.tg.click(Top(a="q", id=150))
    labels = [b.text for b in en.tg.buttons()]
    assert "100 GB — 120,000 Toman" in labels and "500 GB — 450,000 Toman" in labels and "1 TB — 900,000 Toman" in labels
    assert "5000" not in " ".join(labels)                    # only what the API offers

    await en.tg.press("Promo code")
    await en.tg.send("TOPUP40")
    assert "TOPUP40 applied" in en.tg.last_text()
    assert "100 GB — 72,000 Toman" in [b.text for b in en.tg.buttons()]

    await en.tg.press("100 GB")
    t = en.tg.last_text()
    assert "Confirm traffic top-up" in t and "120,000 Toman" in t and "48,000 Toman" in t and "72,000 Toman" in t
    assert en.fake.count("POST", "/services/traffic-topup") == 0

    await en.tg.press("Create invoice")
    assert en.fake.last_body("POST", "/services/traffic-topup") == {"service_id": 150, "gb": 100, "promocode": "TOPUP40"}
    assert "Top-up invoice created" in en.tg.last_text()
    labels = [b.text for b in en.tg.buttons()]
    assert "💰 Pay from Wallet" in labels and "💳 Pay Online" in labels and "₮ Pay with USDT" in labels


async def test_topup_invalid_promo_shows_reason_and_undiscounted_prices(en):
    await en.tg.click(Top(a="q", id=150))
    await en.tg.press("Promo code")
    await en.tg.send("WRONG")
    assert "not valid" in en.tg.last_text() and "without a discount" in en.tg.last_text()
    assert "100 GB — 120,000 Toman" in [b.text for b in en.tg.buttons()]


async def test_topup_bad_promo_format_rejected_locally(en):
    await en.tg.click(Top(a="q", id=150))
    await en.tg.press("Promo code")
    en.tg.reset()
    await en.tg.send("not valid!!")
    assert "Invalid promo code format" in en.tg.last_text() and en.fake.count("GET", "/services/traffic-topup/quote") == 1


# ====================================================================== renewal
async def test_renewal_flow_creates_invoice_without_duplicates(en):
    await en.tg.click(Srv(a="d", id=150))
    await en.tg.press("Renew")
    assert "14 days" in en.tg.last_text()
    await en.tg.press("Promo code")
    await en.tg.send("WELCOME10")
    assert "WELCOME10" in en.tg.last_text() and "Confirm renewal" in en.tg.last_text()
    assert en.fake.count("POST", "/services/renew") == 0
    await en.tg.press("Confirm")
    assert en.fake.last_body("POST", "/services/renew") == {"service_id": 150, "promocode": "WELCOME10"}
    t = en.tg.last_text()
    assert "Renewal invoice issued" in t and "#8902" in t and "1,012,500 Toman" in t and "337,500" in t
    assert any("Pay from Wallet" in b.text for b in en.tg.buttons())

    await en.tg.click("rn:go:150")      # replay / double click → same invoice, flagged as existing
    assert "Existing unpaid renewal invoice" in en.tg.last_text()
    assert sum(1 for i in en.fake.invoices if i["id"] == 8902) == 1


async def test_renewal_not_due_yet_explains_dates(en):
    await en.tg.click("rn:go:151")
    t = en.tg.last_text()
    assert "cannot be renewed yet" in t and "2026-10-19" in t and "2026-11-02" in t and "NOT_DUE_YET" not in t


async def test_renewal_bad_promo_message(fa):
    await fa.tg.click("rn:p:150")
    await fa.tg.send("BADCODE")
    await fa.tg.press("تأیید")
    assert "این کد تخفیف در اینجا قابل استفاده نیست" in fa.tg.last_text()


# ====================================================================== invoices & payment
async def test_invoice_list_filters_and_card_fields(en):
    await en.tg.click(Menu(a="inv"))
    await en.tg.press("Unpaid")
    t = en.tg.last_text()
    assert "#8841" in t and "1,350,000 Toman" in t and "2026-10-08" in t and "Unpaid" in t and "20 most recent" in t
    assert "8800" not in t
    assert en.fake.last_body("GET", "/invoices") == {"status": "Unpaid"}
    await en.tg.click(Inv(a="l", f="a"))
    assert "#8800" in en.tg.last_text()


async def test_invoice_pagination_of_the_20_recent(en):
    for i in range(12):
        en.fake.invoices.append({**en.fake.invoices[1], "id": 7000 + i, "invoicenum": str(7000 + i)})
    await en.tg.click(Inv(a="l", f="a"))
    assert "1/3" in " ".join(b.text for b in en.tg.buttons())
    await en.tg.press("▶️")
    assert "2/3" in " ".join(b.text for b in en.tg.buttons())


async def test_wallet_payment_requires_confirmation_and_shows_math(en):
    await en.tg.click(Inv(a="d", id=8841))
    online = en.tg.find_button("Pay Online")
    assert online.url == "https://pay.example/go/8841"            # official URL button straight from the invoice
    await en.tg.press("Pay from Wallet")
    t = en.tg.last_text()
    assert "#8841" in t and "1,350,000 Toman" in t and "2,000,000 Toman" in t and "650,000 Toman" in t
    assert en.fake.count("POST", "/invoices/pay-credit") == 0
    await en.tg.press("Yes, pay now")
    assert "Invoice paid" in en.tg.last_text() and "650,000 Toman" in en.tg.last_text()
    assert en.fake.wallet == 650_000


async def test_wallet_payment_double_click_pays_once(en):
    data = Inv(a="pd", id=8841)
    await asyncio.gather(en.tg.click(data), en.tg.click(data))
    assert en.fake.count("POST", "/invoices/pay-credit") == 1 and en.fake.wallet == 650_000


async def test_insufficient_wallet_blocks_confirm_and_offers_add_funds(en):
    en.fake.wallet = 1000
    await en.tg.click(Inv(a="pc", id=8841))
    t = en.tg.last_text()
    assert "short by" in t and "1,349,000 Toman" in t
    assert not any("Yes, pay now" in b.text for b in en.tg.buttons())
    assert en.tg.find_button("Add Funds").url == "https://my.trusthost.ir/addfunds"
    assert en.fake.count("POST", "/invoices/pay-credit") == 0


async def test_http_402_at_payment_time_shows_add_funds(en):
    en.fake.overrides["POST /invoices/pay-credit"] = (402, err("INSUFFICIENT_CREDIT"))
    await en.tg.click(Inv(a="pd", id=8841))
    assert "not enough" in en.tg.last_text() and en.tg.find_button("Add Funds").url.startswith("https://")


async def test_pay_already_paid_invoice_is_explained(en):
    await en.tg.click(Inv(a="pc", id=8800))
    assert "no longer unpaid" in en.tg.last_text()
    assert not any("Yes, pay now" in b.text for b in en.tg.buttons())


async def test_usdt_and_online_payment_links(en):
    await en.tg.click(Inv(a="pu", id=8841))
    assert "USDT" in en.tg.last_text() and en.tg.find_button("Open payment page").url == "https://pay.example/usdt/8841"
    assert en.fake.last_body("GET", "/invoices/pay-url") == {"invoice_id": "8841", "gateway": "usdt"}
    await en.tg.click(Inv(a="po", id=8841))
    assert en.tg.find_button("Open payment page").url == "https://pay.example/zarinpal/8841"
    assert "gateway" not in en.fake.last_body("GET", "/invoices/pay-url")
    assert "only once TrustHost confirms" in en.tg.last_text()   # never claims payment yet


async def test_pay_url_for_paid_invoice(en):
    await en.tg.click(Inv(a="po", id=8800))
    assert "already been paid" in en.tg.last_text()


async def test_wallet_screen_uses_official_add_funds_url(en):
    await en.tg.click(Menu(a="wal"))
    assert "2,000,000 Toman" in en.tg.last_text() and "does not allow deposits" in en.tg.last_text()
    assert en.tg.find_button("Add Funds").url == "https://my.trusthost.ir/addfunds"


# ====================================================================== ordering
async def test_full_order_flow_with_dynamic_options_password_and_payment(en):
    tg, fake = en.tg, en.fake
    await tg.click(Menu(a="order"))
    assert "Virtual Servers" in [b.text.replace("📁 ", "") for b in tg.buttons()]
    await tg.press("Virtual Servers")
    await tg.press("VPS Germany")
    assert "4 vCPU" in tg.last_text() and "1350000 IRT" in tg.last_text()
    assert [b.text.split(" · ")[0] for b in tg.buttons()][:2] == ["Monthly", "Quarterly"]   # cycles from the API pricing
    await tg.press("Monthly")

    assert "Step 1/3" in tg.last_text() and "Operating System" in tg.last_text()
    await tg.press("Ubuntu 24.04")
    assert "Extra IPs" in tg.last_text() and "whole number" in tg.last_text()
    await tg.send("abc")
    assert "whole number (0 or more)" in tg.last_text()
    await tg.send("2")
    assert "Purpose" in tg.last_text() and "What for?" in tg.last_text()
    await tg.send("web")
    assert "Optional settings" in tg.last_text()

    await tg.press("Hostname")
    await tg.send("bad_host!")
    assert "Invalid hostname" in tg.last_text()
    await tg.send("SRV1.example.com")
    assert "srv1.example.com" in tg.last_text()

    await tg.press("Root password")
    tg.reset()
    await tg.send("S3cretPass!")
    assert len(tg.deleted()) == 1                                    # password message removed from the chat
    assert "S3cretPass" not in tg.all_text()
    assert "Root password" in " ".join(b.text for b in tg.buttons()) and "✓" in tg.find_button("Root password").text

    await tg.press("Promo code")
    await tg.send("NOPE")
    assert "does not exist" in tg.last_text()
    await tg.send("WELCOME10")
    await tg.press("Gateway")
    assert "USDT" in tg.find_button("Gateway").text
    await tg.press("Review order")
    t = tg.last_text()
    for needle in ("Order summary", "VPS Germany", "Monthly", "Operating System: Ubuntu 24.04", "Extra IPs: 2", "Purpose: web",
                   "srv1.example.com", "Root password: set", "USDT", "1,350,000 Toman", "135,000 Toman", "1,215,000 Toman"):
        assert needle in t, needle
    assert "S3cretPass" not in t
    assert fake.count("POST", "/orders/create") == 0                 # nothing created before confirmation

    await tg.press("Confirm Order")
    body = fake.last_body("POST", "/orders/create")
    assert body["configoptions"] == {"1": 11, "2": 2} and body["customfields"] == {"5": "web"}
    assert body["hostname"] == "srv1.example.com" and body["rootpw"] == "S3cretPass!" and body["payment_method"] == "usdt"
    assert body["promocode"] == "WELCOME10" and body["billingcycle"] == "monthly" and body["product_id"] == 12
    t = tg.last_text()
    assert "Order created" in t and "#9001" in t and "1,215,000 Toman" in t
    assert tg.find_button("Pay Online").url == "https://pay.example/go/x"

    data = await state_data(en)                                      # draft (and password) are gone from memory
    assert "order" not in data and "S3cretPass" not in str(data)

    await tg.press("Pay from Wallet")
    await tg.press("Yes, pay now")
    assert "Invoice paid" in tg.last_text() and fake.wallet == 2_000_000 - 1_215_000


async def test_order_confirm_double_click_creates_one_order(en):
    await en.tg.click(Cat(a="c", pid=12, cy="m"))
    await en.tg.press("Skip")
    await en.tg.press("Skip")
    await en.tg.press("Skip")
    await en.tg.press("Review")
    await asyncio.gather(en.tg.click("o:confirm"), en.tg.click("o:confirm"))
    assert en.fake.count("POST", "/orders/create") == 1
    await en.tg.click("o:confirm")                                   # stale button after success
    assert "session has expired" in en.tg.last_text() and en.fake.count("POST", "/orders/create") == 1


async def test_order_out_of_stock_keeps_draft_and_context(en):
    en.fake.overrides["POST /orders/create"] = (400, err("OUT_OF_STOCK"))
    await en.tg.click(Cat(a="c", pid=12, cy="q"))
    for _ in range(3):
        await en.tg.press("Skip")
    await en.tg.press("Review")
    await en.tg.press("Confirm Order")
    assert "out of stock" in en.tg.last_text()
    await en.tg.press("Back")                                        # back lands on the review screen, draft intact
    assert "Order summary" in en.tg.last_text() and "Quarterly" in en.tg.last_text()


async def test_order_back_cancel_and_cancel_command(en):
    await en.tg.click(Cat(a="c", pid=12, cy="m"))
    await en.tg.press("Ubuntu")
    await en.tg.press("Back")
    assert "Step 2/3" not in en.tg.last_text() and "Step 1/3" in en.tg.last_text()
    await en.tg.press("Back")
    assert "VPS Germany" in en.tg.last_text() and "billing cycle" in en.tg.last_text()   # back to product page
    await en.tg.click(Cat(a="c", pid=12, cy="m"))
    await en.tg.press("Skip (use default)")
    await en.tg.press("Skip")
    await en.tg.press("Skip")
    await en.tg.press("Hostname")
    await en.tg.send("/cancel")                                      # leaves the state, not trapped
    assert "Cancelled" in en.tg.all_text()
    en.tg.reset()
    await en.tg.send("srv1.example.com")                             # no longer consumed as hostname
    assert "Please use the menu" in en.tg.last_text() and (await state_data(en)) == {}


async def test_order_session_expired_after_restart(en):
    await en.tg.click(Cat(a="c", pid=12, cy="m"))
    await en.dp.storage.close()  # not clearing; emulate lost state instead
    key = StorageKey(bot_id=en.bot.id, chat_id=ADMIN_ID, user_id=ADMIN_ID)
    await en.dp.storage.set_data(key, {})
    await en.tg.click("cf:k:0:0")
    assert "session has expired" in en.tg.last_text()


async def test_new_product_in_catalog_appears_without_code_changes(en):
    en.fake.products.append({"id": 77, "group_id": 3, "group_name": "Virtual Servers", "name": "VPS Tokyo 🆕", "type": "vcenter",
                             "paytype": "recurring", "description": [], "pricing": {"annually": "9000000 IRT"}})
    await en.tg.click(Cat(a="l", g=3))
    assert any("VPS Tokyo" in b.text for b in en.tg.buttons())
    await en.tg.click(Cat(a="p", pid=77, g=3))
    cycles = [b.text for b in en.tg.buttons() if b.callback_data and b.callback_data.startswith("c:c:")]
    assert len(cycles) == 1 and cycles[0].startswith("Annual")


async def test_custom_dropdown_and_tickbox_fields_are_rendered(en):
    en.fake.options = {"config_options": [], "custom_fields": [
        {"id": 8, "fieldname": "Location", "fieldtype": "dropdown", "description": "", "fieldoptions": "Berlin,Helsinki"},
        {"id": 9, "fieldname": "Backups", "fieldtype": "tickbox", "description": "", "fieldoptions": ""}]}
    await en.tg.click(Cat(a="c", pid=12, cy="m"))
    assert [b.text for b in en.tg.buttons()][:2] == ["Berlin", "Helsinki"]
    await en.tg.press("Helsinki")
    await en.tg.press("Yes")
    await en.tg.press("Review")
    assert "Location: Helsinki" in en.tg.last_text() and "Backups: ✓" in en.tg.last_text()
    await en.tg.press("Confirm Order")
    assert en.fake.last_body("POST", "/orders/create")["customfields"] == {"8": "Helsinki", "9": "on"}


# ====================================================================== support
async def test_ticket_list_detail_and_reply(en):
    await en.tg.click(Menu(a="support"))
    await en.tg.press("My tickets")
    t = en.tg.last_text()
    assert "#482913" in t and "Answered" in t and "Medium" in t and "Technical Support" in t and "20 most recent" in t
    await en.tg.press("482913")
    t = en.tg.last_text()
    assert "Ticket #482913" in t and "Reverse DNS" in t and "Please set PTR." in t and "Done, please check." in t and "Sara" in t
    await en.tg.press("Reply")
    await en.tg.send("Thanks a lot")
    assert en.fake.last_body("POST", "/tickets/reply") == {"ticket_id": 61, "message": "Thanks a lot"}
    assert "Reply sent" in en.tg.all_text() and "Thanks a lot" in en.tg.last_text() and "👤 You" in en.tg.last_text()


async def test_new_ticket_flow_with_related_service(en):
    await en.tg.click(Menu(a="support"))
    await en.tg.press("New ticket")
    assert [b.text for b in en.tg.buttons()][:2] == ["🏢 Technical Support", "🏢 Billing"]
    await en.tg.press("Billing")
    await en.tg.send("Invoice question")
    await en.tg.send("Why was I charged twice?")
    assert "Choose the priority" in en.tg.last_text()
    await en.tg.press("High")
    await en.tg.press("VPS Germany")
    t = en.tg.last_text()
    assert "Billing" in t and "Invoice question" in t and "High" in t and "VPS Germany" in t and "charged twice" in t
    assert en.fake.count("POST", "/tickets/create") == 0
    await en.tg.press("Submit")
    assert en.fake.last_body("POST", "/tickets/create") == {"dept_id": 3, "subject": "Invoice question", "message": "Why was I charged twice?", "priority": "High", "service_id": 150}
    assert "Ticket <b>#7762</b> created" in en.tg.last_text()


async def test_ticket_from_server_screen_skips_service_step(en):
    await en.tg.click(Srv(a="d", id=150))
    await en.tg.press("Support")
    await en.tg.press("Technical")
    await en.tg.send("Slow disk")
    await en.tg.send("It is slow")
    await en.tg.press("Low")
    assert "Review ticket" in en.tg.last_text() and "VPS Germany" in en.tg.last_text()


async def test_ticket_input_validation_and_cancel(en):
    await en.tg.click("nt:s:0:0:0")
    await en.tg.press("Billing")
    await en.tg.send("x" * 300)
    assert "1–200 characters" in en.tg.last_text()
    await en.tg.send("/cancel")
    assert (await state_data(en)) == {}
    assert en.fake.count("POST", "/tickets/create") == 0


async def test_ticket_not_found_is_friendly(en):
    await en.tg.click(Tkt(a="d", id=555))
    assert "ticket was not found" in en.tg.last_text()


# ====================================================================== settings / health / help
async def test_notification_toggles_persist(en):
    await en.tg.click("st:notif:")
    assert "✅ Ticket replies" in [b.text for b in en.tg.buttons()]
    await en.tg.press("Ticket replies")
    assert "❌ Ticket replies" in [b.text for b in en.tg.buttons()]
    assert (await en.repo.get_or_create_user(ADMIN_ID)).notify_tickets is False
    await en.tg.press("Ticket replies")
    assert (await en.repo.get_or_create_user(ADMIN_ID)).notify_tickets is True


async def test_health_screen_never_shows_credentials(en):
    await en.tg.send("/health")
    t = en.tg.last_text()
    assert "Telegram: ✅ OK" in t and "Database: ✅ OK" in t and "TrustHost API: ✅ OK" in t and "Response time" in t
    assert "my.trusthost.ir" in t and "th_res_" not in t and "th_sec_" not in t
    en.fake.overrides["GET /wallet"] = (401, err("UNAUTHORIZED"))
    await en.tg.send("/health")
    assert "TrustHost API: ❌" in en.tg.last_text() and "UNAUTHORIZED" in en.tg.last_text()


async def test_help_and_unavailable_features_are_honest(en):
    await en.tg.send("/help")
    assert "/servers" in en.tg.last_text() and "/cancel" in en.tg.last_text()
    await en.tg.click("st:lim:")
    t = en.tg.last_text()
    assert "not available through the TrustHost Customer API" in t and "reinstalling" in t


async def test_all_documented_commands_respond(en):
    for cmd in ("/start", "/menu", "/servers", "/orders", "/invoices", "/wallet", "/usage", "/support", "/settings", "/help", "/cancel"):
        en.tg.reset()
        await en.tg.send(cmd)
        assert en.tg.sent(), cmd
        assert "Please use the menu" not in en.tg.last_text(), cmd


# ====================================================================== error UX
async def test_rate_limit_message_has_retry_seconds_and_stops_calling(en):
    en.fake.overrides["GET /services"] = (429, err("RATE_LIMITED"), {"Retry-After": "37"})
    await en.tg.click(Menu(a="srv"))
    assert "37 seconds" in en.tg.last_text()
    n = len(en.fake.calls)
    await en.tg.click(Menu(a="srv"))                                 # cooling down → no new network call
    assert len(en.fake.calls) == n and "seconds" in en.tg.last_text()


async def test_auth_failure_message_is_exact_and_leaks_nothing(fa):
    fa.fake.overrides["GET /services"] = (401, err("UNAUTHORIZED", f"secret th_sec_TESTSECRET0123456789"))
    await fa.tg.click(Menu(a="srv"))
    assert fa.tg.last_text() == "❌ احراز هویت با TrustHost انجام نشد."
    assert "th_sec_" not in fa.tg.all_text()


async def test_unexpected_exception_is_contained(en):
    async def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise RuntimeError("kaboom th_sec_TESTSECRET0123456789")
    en.hub.servers.services = boom  # type: ignore[assignment]
    await en.tg.click(Menu(a="srv"))
    assert "Something went wrong" in en.tg.last_text() and "kaboom" not in en.tg.all_text()


async def test_connection_error_message(en):
    import httpx
    def down(req):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("down", request=req)
    en.hub.client._http._transport = httpx.MockTransport(down)  # type: ignore[attr-defined]
    await en.tg.click(Menu(a="srv"))
    assert "could not be reached" in en.tg.last_text()


# ====================================================================== Persian UI sweep
async def test_persian_screens_have_no_untranslated_keys_or_english_errors(fa):
    tg = fa.tg
    screens = [lambda: tg.send("/start"), lambda: tg.click(Menu(a="srv")), lambda: tg.click(Srv(a="d", id=150)),
               lambda: tg.click(Srv(a="st", id=150)), lambda: tg.click(Srv(a="tr", id=150)), lambda: tg.click(Srv(a="us", id=150)),
               lambda: tg.click(Srv(a="pw", id=150)), lambda: tg.click(Pow(a="ask", id=150, act="off")),
               lambda: tg.click(Top(a="q", id=150)), lambda: tg.click("tp:s:150:100"), lambda: tg.click("rn:s:150"),
               lambda: tg.click(Menu(a="inv")), lambda: tg.click(Inv(a="l", f="a")), lambda: tg.click(Inv(a="d", id=8841)),
               lambda: tg.click(Inv(a="pc", id=8841)), lambda: tg.click(Menu(a="wal")), lambda: tg.click(Menu(a="order")),
               lambda: tg.click(Cat(a="l", g=3)), lambda: tg.click(Cat(a="p", pid=12, g=3)), lambda: tg.click(Cat(a="c", pid=12, cy="m")),
               lambda: tg.click(Menu(a="support")), lambda: tg.click(Tkt(a="l")), lambda: tg.click(Tkt(a="d", id=61)),
               lambda: tg.click("nt:s:0:0:0"), lambda: tg.click(Menu(a="settings")), lambda: tg.click("st:notif:"),
               lambda: tg.click("st:lim:"), lambda: tg.click("st:api:"), lambda: tg.send("/help")]
    for go in screens:
        tg.reset()
        await go()
        text = "\n".join(r.text for r in tg.sent()) + "\n" + " ".join(b.text for r in tg.sent() for b in tg.buttons(r))
        leaked = [k for k in CATALOGS["en"] if re.search(rf"(?<![\w.]){re.escape(k)}(?![\w])", text)]
        assert not leaked, leaked
        assert re.search(r"[\u0600-\u06FF]", text), "no Persian in screen"
