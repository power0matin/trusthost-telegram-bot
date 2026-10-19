"""Test doubles: a fake TrustHost HTTP server (httpx.MockTransport) and a fake Telegram session."""
from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from typing import Any, Callable

import httpx
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery, DeleteMessage, EditMessageText, GetMe, SendMessage, SetMyCommands,
)
from aiogram.types import Chat, Message, User

API_KEY = "th_res_TESTKEY0123456789"
API_SECRET = "th_sec_TESTSECRET0123456789"
BOT_TOKEN = "123456789:AAEhBOweik6ad9r_QXMENQjcrGbqCr4K-RQ"


def ok(**kw: Any) -> dict[str, Any]:
    return {"success": True, **kw}


def err(code: str, message: str = "پیام", **kw: Any) -> dict[str, Any]:
    return {"success": False, "error": code, "message": message, **kw}


class FakeTrustHost:
    """Behaves like the documented API. `overrides['METHOD /path']` forces (status, payload[, headers])."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.headers_seen: list[dict[str, str]] = []
        self.overrides: dict[str, Any] = {}
        self.wallet = 2_000_000
        self.power_state = "POWERED_ON"
        self.pending_power: tuple[str, int] | None = None  # (target state, polls until applied)
        self.services = [
            {"id": 150, "product_name": "VPS Germany", "servertype": "vcenter", "domain": "srv.example.com",
             "dedicatedip": "203.0.113.10", "assignedips": "203.0.113.10", "amount": "1350000.00",
             "billingcycle": "Monthly", "nextduedate": "2026-10-21", "status": "Active"},
            {"id": 151, "product_name": "VPS Finland", "servertype": "vcenter", "domain": "",
             "dedicatedip": "203.0.113.11", "assignedips": "", "amount": "900000.00",
             "billingcycle": "Quarterly", "nextduedate": "2026-11-02", "status": "Suspended"},
        ]
        self.invoices: list[dict[str, Any]] = [
            {"id": 8841, "invoicenum": "8841", "date": "2026-10-01", "duedate": "2026-10-08", "subtotal": 1350000,
             "credit": 0, "total": 1350000, "status": "Unpaid", "payment_url": "https://pay.example/view/8841",
             "direct_payment_url": "https://pay.example/go/8841"},
            {"id": 8800, "invoicenum": "8800", "date": "2026-09-01", "duedate": "2026-09-08", "subtotal": 900000,
             "credit": 0, "total": 900000, "status": "Paid", "payment_url": None, "direct_payment_url": None},
        ]
        self.tickets: list[dict[str, Any]] = [
            {"id": 61, "tid": "482913", "department": "Technical Support", "subject": "Reverse DNS",
             "status": "Answered", "priority": "Medium", "lastreply": "2026-10-04 10:00:00", "date": "2026-10-03 09:00:00"},
        ]
        self.ticket_replies: dict[int, list[dict[str, Any]]] = {
            61: [{"id": 1, "admin": "Sara", "name": "Sara", "message": "Done, please check.", "date": "2026-10-04 10:00:00"}]}
        self.next_invoice = 9000
        self.next_ticket = 62
        self.orders: list[dict[str, Any]] = []
        self.products = [
            {"id": 12, "group_id": 3, "group_name": "Virtual Servers", "name": "VPS Germany", "type": "vcenter",
             "paytype": "recurring", "description": ["4 vCPU", "8 GB RAM", "120 GB SSD"],
             "pricing": {"monthly": "1350000 IRT", "quarterly": "3900000 IRT"}},
        ]
        self.options = {
            "config_options": [
                {"id": 1, "name": "Operating System", "type": 1,
                 "sub_options": [{"id": 11, "name": "Ubuntu 24.04"}, {"id": 12, "name": "Debian 12"}]},
                {"id": 2, "name": "Extra IPs", "type": 4, "sub_options": []},
            ],
            "custom_fields": [{"id": 5, "fieldname": "Purpose", "fieldtype": "text", "description": "What for?", "fieldoptions": ""}],
        }

    # -------------------------------------------------------------- plumbing
    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        method = request.method
        body = json.loads(request.content) if request.content else {}
        params = dict(request.url.params)
        self.calls.append((method, path, body or params))
        self.headers_seen.append(dict(request.headers))
        if request.headers.get("x-reseller-key") != API_KEY or request.headers.get("x-reseller-secret") != API_SECRET:
            return httpx.Response(401, json=err("UNAUTHORIZED", "کلید نامعتبر"))
        key = f"{method} {path}"
        if key in self.overrides:
            o = self.overrides[key]
            if callable(o):
                o = o(body or params)
            status, payload, *hdr = o
            return httpx.Response(status, json=payload, headers=(hdr[0] if hdr else {}))
        handler = getattr(self, "h_" + path.strip("/").replace("/", "_").replace("-", "_"), None)
        if handler is None or method != ("POST" if path in self.POST_ROUTES else "GET"):
            return httpx.Response(405, json=err("METHOD_NOT_ALLOWED"))
        status, payload = handler(body or params)
        return httpx.Response(status, json=payload)

    POST_ROUTES = {"/orders/validate-promo", "/orders/create", "/invoices/pay-credit", "/services/renew",
                   "/services/power", "/services/traffic-topup", "/tickets/create", "/tickets/reply"}

    def count(self, method: str, path: str) -> int:
        return sum(1 for m, p, _ in self.calls if m == method and p == path)

    def last_body(self, method: str, path: str) -> dict[str, Any]:
        return [b for m, p, b in self.calls if m == method and p == path][-1]

    def _service(self, p: dict[str, Any]) -> dict[str, Any] | None:
        sid = int(p.get("service_id", 0))
        return next((s for s in self.services if s["id"] == sid), None)

    # -------------------------------------------------------------- catalog
    def h_catalog_groups(self, p):  # noqa: ANN001
        return 200, ok(groups=[{"id": 3, "name": "Virtual Servers", "headline": "", "tagline": ""}])

    def h_catalog_products(self, p):  # noqa: ANN001
        items = [x for x in self.products if (not p.get("group_id") or x["group_id"] == int(p["group_id"]))
                 and (not p.get("product_id") or x["id"] == int(p["product_id"]))]
        out = ok(products=items)
        if p.get("promocode"):
            out["promo"] = self._promo(p["promocode"])
        return 200, out

    def h_catalog_options(self, p):  # noqa: ANN001
        return 200, ok(**self.options)

    def _promo(self, code: str) -> dict[str, Any]:
        if code.upper() == "WELCOME10":
            return {"success": True, "valid": True, "code": "WELCOME10", "type": "Percentage", "value": 10,
                    "original_amount": 1350000, "discount_amount": 135000, "final_amount": 1215000}
        if code.upper() == "TRAFFICONLY":
            return {"success": False, "valid": False, "error": "PROMO_TRAFFIC_ONLY", "message": "x"}
        return {"success": False, "valid": False, "error": "PROMO_NOT_FOUND", "message": "x"}

    # -------------------------------------------------------------- orders
    def h_orders_validate_promo(self, p):  # noqa: ANN001
        return 200, self._promo(p.get("promocode", ""))

    def h_orders_create(self, p):  # noqa: ANN001
        if p.get("promocode") and not self._promo(p["promocode"])["valid"]:
            return 400, err(self._promo(p["promocode"])["error"])
        for o in self.orders:
            if o["product_id"] == p["product_id"] and self._invoice(o["invoice_id"])["status"] == "Unpaid":
                return 200, ok(order_id=o["order_id"], invoice_id=o["invoice_id"], total=o["total"], status="Unpaid",
                               is_duplicate=True, product_name="VPS Germany", discount_amount=0)
        self.next_invoice += 1
        disc = 135000 if p.get("promocode") else 0
        order = {"order_id": 5000 + len(self.orders), "invoice_id": self.next_invoice, "total": 1350000 - disc,
                 "product_id": p["product_id"], "payload": p}
        self.orders.append(order)
        self.invoices.insert(0, {"id": order["invoice_id"], "invoicenum": str(order["invoice_id"]), "date": "2026-10-06",
                                 "duedate": "2026-10-13", "subtotal": 1350000, "credit": 0, "total": order["total"],
                                 "status": "Unpaid", "payment_url": "https://pay.example/view/x",
                                 "direct_payment_url": "https://pay.example/go/x"})
        return 200, ok(order_id=order["order_id"], invoice_id=order["invoice_id"], total=order["total"], status="Unpaid",
                       payment_url="https://pay.example/view/x", direct_payment_url="https://pay.example/go/x",
                       payment_method=p.get("payment_method") or "zarinpal", promocode=p.get("promocode"),
                       discount_amount=disc, product_name="VPS Germany", domain="", is_duplicate=False)

    # -------------------------------------------------------------- billing
    def _invoice(self, iid: int) -> dict[str, Any]:
        return next(i for i in self.invoices if i["id"] == iid)

    def h_invoices(self, p):  # noqa: ANN001
        rows = [i for i in self.invoices if not p.get("status") or i["status"] == p["status"]]
        return 200, ok(invoices=rows[:20])

    def h_invoices_pay_url(self, p):  # noqa: ANN001
        inv = next((i for i in self.invoices if i["id"] == int(p.get("invoice_id", 0))), None)
        if inv is None:
            return 404, err("INVOICE_NOT_FOUND")
        if inv["status"] != "Unpaid":
            return 200, err("ALREADY_PAID")
        gw = "usdt" if p.get("gateway") == "usdt" else "zarinpal"
        return 200, ok(invoice_id=inv["id"], gateway=gw, direct_payment_url=f"https://pay.example/{gw}/{inv['id']}",
                       amount=inv["total"])

    def h_invoices_pay_credit(self, p):  # noqa: ANN001
        inv = next((i for i in self.invoices if i["id"] == int(p.get("invoice_id", 0))), None)
        if inv is None:
            return 404, err("INVOICE_NOT_FOUND")
        if inv["status"] != "Unpaid":
            return 409, err("INVOICE_NOT_UNPAID")
        if self.wallet < inv["total"]:
            return 402, err("INSUFFICIENT_CREDIT", balance=self.wallet, required=inv["total"])
        self.wallet -= inv["total"]
        inv["status"] = "Paid"
        return 200, ok(invoice_id=inv["id"], amount_paid=inv["total"], status="Paid", wallet_balance=self.wallet)

    def h_wallet(self, p):  # noqa: ANN001
        return 200, ok(balance=self.wallet, add_funds_url="https://my.trusthost.ir/addfunds")

    # -------------------------------------------------------------- services
    def h_services(self, p):  # noqa: ANN001
        return 200, ok(services=self.services)

    def h_services_renew(self, p):  # noqa: ANN001
        s = self._service(p)
        if s is None:
            return 404, err("SERVICE_NOT_FOUND")
        if s["id"] == 151:
            return 409, err("NOT_DUE_YET", next_due_date="2026-11-02", next_invoice_date="2026-10-19")
        if p.get("promocode") and p["promocode"].upper() != "WELCOME10":
            return 422, err("PROMO_NOT_APPLICABLE")
        existing = next((i for i in self.invoices if i["id"] == 8902), None)
        if existing:
            return 200, ok(service_id=150, invoice_id=8902, total=existing["total"], due_date="2026-10-21", created=False)
        total = 1350000 - (337500 if p.get("promocode") else 0)
        self.invoices.insert(0, {"id": 8902, "invoicenum": "8902", "date": "2026-10-06", "duedate": "2026-10-21",
                                 "subtotal": 1350000, "credit": 0, "total": total, "status": "Unpaid",
                                 "payment_url": None, "direct_payment_url": None})
        out = ok(service_id=150, invoice_id=8902, total=total, due_date="2026-10-21", created=True)
        if p.get("promocode"):
            out["promo"] = {"code": p["promocode"], "discount": 337500}
        return 200, out

    def h_services_status(self, p):  # noqa: ANN001
        s = self._service(p)
        if s is None:
            return 404, err("SERVICE_NOT_FOUND")
        if self.pending_power:
            target, polls = self.pending_power
            if polls <= 0:
                self.power_state, self.pending_power = target, None
            else:
                self.pending_power = (target, polls - 1)
        return 200, ok(service_id=s["id"], service_status=s["status"], power_state=self.power_state, cpu=4,
                       ram_mb=8192, disk_gb=120, ip=s["dedicatedip"])

    def h_services_power(self, p):  # noqa: ANN001
        s = self._service(p)
        if s is None:
            return 404, err("SERVICE_NOT_FOUND")
        if p.get("action") not in ("on", "off", "shutdown", "reboot"):
            return 400, err("INVALID_ACTION")
        if s["status"] != "Active":
            return 409, err("SERVICE_NOT_ACTIVE", service_status=s["status"])
        target = {"on": "POWERED_ON", "off": "POWERED_OFF", "shutdown": "POWERED_OFF", "reboot": "POWERED_ON"}[p["action"]]
        self.pending_power = (target, 1)
        return 200, ok(service_id=s["id"], action=p["action"], message="queued")

    def h_services_traffic(self, p):  # noqa: ANN001
        s = self._service(p)
        if s is None:
            return 404, err("SERVICE_NOT_FOUND")
        return 200, ok(service_id=s["id"], unit="GiB", used_gb=412.37, download_gb=412.37, upload_gb=58.2, limit_gb=1000,
                       unlimited=False, remaining_gb=587.63, percent_used=41.2, period_start="2026-09-21 00:00:00",
                       period_end=None, data_status="ok", last_synced_at="2026-09-21 19:40:00")

    def h_services_usage(self, p):  # noqa: ANN001
        s = self._service(p)
        if s is None:
            return 404, err("SERVICE_NOT_FOUND")
        days = int(p.get("days", 30))
        if not 1 <= days <= 90:
            return 400, err("INVALID_DAYS")
        items = [{"date": f"2026-09-{d:02d}", "inbound_gb": d * 1.5, "outbound_gb": d * 0.2} for d in range(1, min(days, 28) + 1)]
        return 200, ok(service_id=s["id"], service_status=s["status"],
                       resources={"available": True, "power_state": "POWERED_ON", "cpu_cores": 4, "cpu_usage_mhz": 1450,
                                  "ram_mb": 8192, "ram_used_mb": 2310, "ram_percent": 28.2, "disk_gb": 120,
                                  "disk_used_gb": 41.75, "uptime_seconds": 864000},
                       traffic={"unit": "GiB", "inbound_gb": 412.37, "outbound_gb": 58.2, "billable": "inbound",
                                "limit_gb": 1000, "unlimited": False, "remaining_gb": 587.63, "percent_used": 41.2,
                                "period_start": "2026-09-21 00:00:00", "period_end": None, "data_status": "ok",
                                "last_synced_at": "2026-09-21 19:40:00"},
                       daily_traffic={"unit": "GiB", "from": "2026-09-01", "to": "2026-09-28", "items": items})

    TOPUP = [(100, 120000), (500, 450000), (1000, 900000)]

    def h_services_traffic_topup_quote(self, p):  # noqa: ANN001
        s = self._service(p)
        if s is None:
            return 404, err("SERVICE_NOT_FOUND")
        code = p.get("promocode")
        promo = None
        disc = 0.4 if code and code.upper() == "TOPUP40" else 0
        if code:
            promo = {"valid": bool(disc), "code": code, "error": None if disc else "PROMO_INVALID", "message": "x"}
        opts = [{"gb": gb, "price": price, "discount": int(price * disc), "total": price - int(price * disc)} for gb, price in self.TOPUP]
        return 200, ok(service_id=s["id"], currency="IRT", options=opts, promo=promo)

    def h_services_traffic_topup(self, p):  # noqa: ANN001
        s = self._service(p)
        if s is None:
            return 404, err("SERVICE_NOT_FOUND")
        tier = dict(self.TOPUP).get(int(p.get("gb", 0)))
        if tier is None:
            return 400, err("TRAFFIC_TIER_UNAVAILABLE")
        if p.get("promocode") and p["promocode"].upper() != "TOPUP40":
            return 422, err("PROMO_INVALID")
        disc = int(tier * 0.4) if p.get("promocode") else 0
        self.next_invoice += 1
        self.invoices.insert(0, {"id": self.next_invoice, "invoicenum": str(self.next_invoice), "date": "2026-10-06",
                                 "duedate": "2026-10-13", "subtotal": tier, "credit": 0, "total": tier - disc,
                                 "status": "Unpaid", "payment_url": None, "direct_payment_url": None})
        return 200, ok(service_id=s["id"], gb=p["gb"], invoice_id=self.next_invoice, price=tier, discount=disc,
                       total=tier - disc, status="Unpaid")

    # -------------------------------------------------------------- tickets
    def h_tickets(self, p):  # noqa: ANN001
        return 200, ok(tickets=self.tickets[:20])

    def h_tickets_departments(self, p):  # noqa: ANN001
        return 200, ok(departments=[{"id": 2, "name": "Technical Support", "description": "Server issues"},
                                    {"id": 3, "name": "Billing", "description": "Invoices & payments"}])

    def h_tickets_details(self, p):  # noqa: ANN001
        tk = next((t for t in self.tickets if t["id"] == int(p.get("ticket_id", 0))), None)
        if tk is None:
            return 200, err("TICKET_NOT_FOUND")
        return 200, ok(ticket={"id": tk["id"], "tid": tk["tid"], "department": tk["department"], "subject": tk["subject"],
                               "status": tk["status"], "message": "Please set PTR.", "date": tk["date"]},
                       replies=self.ticket_replies.get(tk["id"], []))

    def h_tickets_create(self, p):  # noqa: ANN001
        if not p.get("subject") or not p.get("message"):
            return 400, err("EMPTY_FIELDS")
        tid = self.next_ticket
        self.next_ticket += 1
        self.tickets.insert(0, {"id": tid, "tid": f"77{tid}", "department": "Technical Support", "subject": p["subject"],
                                "status": "Open", "priority": p.get("priority", "Medium"),
                                "lastreply": "2026-10-06 12:00:00", "date": "2026-10-06 12:00:00"})
        return 200, ok(ticket_id=tid, tid=f"77{tid}")

    def h_tickets_reply(self, p):  # noqa: ANN001
        tk = next((t for t in self.tickets if t["id"] == int(p.get("ticket_id", 0))), None)
        if tk is None:
            return 400, err("TICKET_NOT_FOUND")
        self.ticket_replies.setdefault(tk["id"], []).append(
            {"id": 99, "admin": "", "name": "You", "message": p["message"], "date": "2026-10-06 12:30:00"})
        tk["status"], tk["lastreply"] = "Customer-Reply", "2026-10-06 12:30:00"
        return 200, ok()


def make_transport(fake: FakeTrustHost) -> httpx.MockTransport:
    return httpx.MockTransport(fake)


# ====================================================================== Telegram
class FakeSession(BaseSession):
    """Records every Bot API call and fabricates minimal valid results."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[Any] = []
        self._ids = iter(range(1000, 10**6))
        self.fail_delete = False

    async def close(self) -> None: ...

    async def stream_content(self, *a: Any, **k: Any):  # type: ignore[no-untyped-def]
        yield b""

    async def make_request(self, bot: Bot, method: Any, timeout: Any = None) -> Any:
        self.requests.append(method)
        now = datetime.now()
        if isinstance(method, (SendMessage, EditMessageText)):
            chat_id = getattr(method, "chat_id", 1) or 1
            mid = getattr(method, "message_id", None) or next(self._ids)
            return Message(message_id=mid, date=now, chat=Chat(id=chat_id, type="private"), text=method.text)
        if isinstance(method, GetMe):
            return User(id=999, is_bot=True, first_name="bot", username="bot")
        if isinstance(method, (DeleteMessage, AnswerCallbackQuery, SetMyCommands)):
            return True
        return True


class Telegram:
    """Drives a Dispatcher with raw updates, as Telegram would."""

    def __init__(self, dp: Any, bot: Bot, session: FakeSession, user_id: int = 111, lang_code: str = "en") -> None:
        self.dp, self.bot, self.session = dp, bot, session
        self.user_id, self.lang_code = user_id, lang_code
        self._uid = 0
        self.message_id = 500

    def _from(self, uid: int | None = None) -> dict[str, Any]:
        return {"id": uid or self.user_id, "is_bot": False, "first_name": "T", "language_code": self.lang_code}

    def _msg(self, uid: int | None, text: str | None) -> dict[str, Any]:
        d: dict[str, Any] = {"message_id": self.message_id, "date": 1_700_000_000,
                             "chat": {"id": uid or self.user_id, "type": "private"}, "from": self._from(uid)}
        if text is not None:
            d["text"] = text
            if text.startswith("/"):
                d["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        return d

    async def send(self, text: str, uid: int | None = None) -> None:
        self._uid += 1
        self.message_id += 1
        await self.dp.feed_raw_update(self.bot, {"update_id": self._uid, "message": self._msg(uid, text)})

    async def click(self, data: Any, uid: int | None = None) -> None:
        self._uid += 1
        packed = data if isinstance(data, str) else data.pack()
        assert len(packed.encode()) <= 64, f"callback data too long: {packed}"
        upd = {"update_id": self._uid, "callback_query": {
            "id": str(self._uid), "from": self._from(uid), "chat_instance": "x", "data": packed,
            "message": self._msg(uid, "prev")}}
        await self.dp.feed_raw_update(self.bot, upd)

    # ---- inspection
    def sent(self) -> list[Any]:
        return [r for r in self.session.requests if isinstance(r, (SendMessage, EditMessageText))]

    def last(self) -> Any:
        return self.sent()[-1]

    def last_text(self) -> str:
        return self.last().text

    def all_text(self) -> str:
        return "\n".join(r.text for r in self.sent())

    def buttons(self, req: Any = None) -> list[Any]:
        req = req or self.last()
        markup = req.reply_markup
        return [b for row in markup.inline_keyboard for b in row] if markup else []

    def button_data(self, req: Any = None) -> list[str]:
        return [b.callback_data for b in self.buttons(req) if b.callback_data]

    def find_button(self, needle: str, req: Any = None) -> Any:
        for b in self.buttons(req):
            if needle in b.text:
                return b
        raise AssertionError(f"button containing {needle!r} not found in {[b.text for b in self.buttons(req)]}")

    async def press(self, needle: str) -> None:
        b = self.find_button(needle)
        assert b.callback_data, f"{needle!r} is a URL button"
        await self.click(b.callback_data)

    def deleted(self) -> list[Any]:
        return [r for r in self.session.requests if isinstance(r, DeleteMessage)]

    def reset(self) -> None:
        self.session.requests.clear()
