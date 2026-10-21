# TrustHost Customer API 1.3.3 → Telegram feature matrix

Source of truth: the official *TrustHost Customer API (1.3.3)* reference. Every documented route is listed; nothing else is called.
The **API version** (1.3.3) is the specification the bot targets; the **bot version** is `app.__version__` (`0.2.0`). They are independent.

**Base URL:** `https://my.trusthost.co/api/v1` (the former `https://my.trusthost.ir/api/v1` still answers directly, so existing `.env` files keep working).
There is no `/v1.3.3` path segment in the documentation, so none is used.

Status: **UI** = reachable from Telegram · **client** = implemented and tested in `app/trusthost/client.py`, deliberately not exposed in Telegram · **unused** = not called.
Risk: **R** read-only · **W** state change (no money) · **$** creates an invoice · **$$** spends money · **!** can interrupt a running server.

| # | Method & route | Parameters | Response (key fields) | Documented errors | Status / Telegram feature | Risk |
|---|---|---|---|---|---|---|
| 1 | GET `/catalog/groups` | filters¹ | `groups[id,name,slug,…,category…,categories,plan_types,cpu_types,product_count]` | 400 `INVALID_<FIELD>` 401 429 | UI: order → groups (hourly-only groups still listed; products are filtered) · filters: client | R |
| 2 | GET `/catalog/products` | `group_id`, `product_id`, filters¹, `promocode`+`billingcycle` (needs `product_id`) | `products[…, in_stock, stock, setup_fees, cycles, hourly{…}]`, `promo` | 400 401 429 | UI: products / detail / cycles; **hourly products hidden** | R |
| 3 | GET `/catalog/options` | `product_id`* | `config_options[…]`, `custom_fields[…]` | 400 401 | UI: dynamic order steps | R |
| 4 | POST `/orders/validate-promo` | `product_id`*, `promocode`*, `billingcycle` | `valid, error, code, type, value, *_amount, message` | always 200 – check `valid`; 401 | UI: promo preview | R |
| 5 | POST `/orders/create` | `product_id`*, `billingcycle` (+`biennially`,`triennially`,`hourly`), `promocode`, `payment_method`, `configoptions`, `customfields`, `domain`, `hostname`, `rootpw` | `order_id, invoice_id, total, status, *_url, is_duplicate` | 400 (`PRODUCT_NOT_FOUND`,`INVALID_BILLING_CYCLE`,`ORDER_CREATION_FAILED`, promo) 401 **402** `INSUFFICIENT_CREDIT` **409** `OUT_OF_STOCK` | UI (monthly…annually); `hourly` accepted by the client only | $ |
| 6 | GET `/invoices` | `status`, **`limit` 1–100**, **`page`** | `invoices[…]`, **`pagination{page,limit,total,has_more}`** | 401 | UI: reads one page of up to 100, paginated locally | R |
| 7 | GET `/invoices/details` **new** | `invoice_id`* | `invoice{…, datepaid, amount_paid, balance, items[], payments[]}` | 400 401 404 `INVOICE_NOT_FOUND` | UI: invoice screen / pay preview (replaces the list lookup) | R |
| 8 | GET `/invoices/pay-url` | `invoice_id`*, `gateway`(`usdt`) | `direct_payment_url, amount, gateway, gateway_title, authority` | 400 401 404 · `ALREADY_PAID` (200, success:false) | UI: "Pay online" / USDT | R |
| 9 | POST `/invoices/pay-credit` | `invoice_id`* | `amount_paid, status, wallet_balance` | 400 401 402 404 409 (`INVOICE_NOT_UNPAID`,`NOTHING_DUE`,`BUSY`) | UI: wallet payment with confirmation | $$ |
| 10 | GET `/wallet` | – | `balance, add_funds_url` | 401 | UI | R |
| 11 | POST `/wallet/topup` **new** | `amount`* (≥ 10000 Toman), `gateway`(`usdt`) | `invoice_id, amount, payment_method, payment_url, direct_payment_url` | 401 · `MINIMUM_AMOUNT` (200, success:false) | UI: wallet → "Top up wallet" (amount → card/USDT → invoice). Not payable from the wallet | $ |
| 12 | GET `/services` | filters¹, `status` | `services[…, category…, traffic{}]` | 400 401 | UI: My Servers | R |
| 13 | GET `/services/details` **new** | `service_id`* | `service{…, ip, regdate, days_remaining, cpu, ram, disk, os, power_state, can_*, has_password, traffic, config_options}` | 400 401 · `SERVICE_NOT_FOUND` (200) | client | R |
| 14 | GET `/services/credentials` **new** | `service_id`* | `ip, username, password, port` | 400 401 · `SERVICE_NOT_FOUND` (200) | client only – **not exposed** (secret over chat history); never cached, password registered for log redaction | R (sensitive) |
| 15 | POST `/services/cancel` **new** | `service_id`*, `type` (`End of Billing Period`/`Immediate`), `reason` | `already_exists, type, message` | 400 401 · `SERVICE_NOT_FOUND`,`ALREADY_CANCELLED` (200) | client only – **not exposed** (destructive; needs its own confirmation design) | $$ (irreversible) |
| 16 | POST `/services/renew` | `service_id`*, `promocode`, **`gateway`** | **`is_existing`**, `product_name`, `domain`, `payment_method`, `*_url`, `promo{code,discount}`, `status`, `total` | 400 401 409 (`SERVICE_NOT_ACTIVE`,`NOT_RENEWABLE`,`PROMO_ALREADY_APPLIED`,`INVOICE_NOT_UNPAID`) **422** promo | UI: renew (shows Paid when a promo covers the invoice) | $ |
| 17 | GET `/services/status` | `service_id`* | `service_status, power_state, cpu, ram_mb, disk_gb, ip` | 400 401 404 409 | UI | R |
| 18 | POST `/services/power` | `service_id`*, `action`* (`on/off/shutdown/reboot`) | `message` (async) | 400 401 404 409 **502** `ACTION_FAILED` | UI: confirm + status polling; 502 → "provider did not accept the command" | ! |
| 19 | POST `/services/action` | – | – | – | **unused** – documented as *Deprecated*; `/services/power` is used | – |
| 20 | GET `/services/traffic` | `service_id`* | `used_gb … data_status` | 400 401 404 | UI | R |
| 21 | GET `/services/usage` | `service_id`*, `days` 1–90 | `resources{}`, `traffic{… billable}`, `daily_traffic{}` | 400 401 404 409 | UI | R |
| 22 | GET `/services/traffic-topup/quote` | `service_id`*, `promocode` | `options[gb,price,discount,total]`, `promo{}` | 400 401 404 | UI | R |
| 23 | POST `/services/traffic-topup` | `service_id`*, `gb`*, `promocode` | `invoice_id, price, discount, total, status` | 400 401 404 409 422 | UI | $ |
| 24 | GET `/tickets` | – | `tickets[…]` (20 most recent) | 401 | UI | R |
| 25 | GET `/tickets/departments` | – | `departments[]` | 401 | UI | R |
| 26 | GET `/tickets/details` | `ticket_id`* | `ticket{…, attachment}`, `replies[…, attachment]` | 401 · `TICKET_NOT_FOUND` (200) | UI | R |
| 27 | POST `/tickets/create` | `subject`*, `message`*, `dept_id`, `priority`, `service_id`, **`attachment{name,content_b64}`** | `ticket_id, tid` | 400 (`EMPTY_FIELDS`,`TICKET_CREATE_FAILED`) 401 | UI (text); attachments: client | W |
| 28 | POST `/tickets/reply` | `ticket_id`*, `message`*, **`attachment`** | `message` | 400 (`TICKET_NOT_FOUND`,`TICKET_REPLY_FAILED`) 401 | UI (text); attachments: client | W |
| 29 | POST `/tickets/close` **new** | `ticket_id`* | `message` | 400 401 · `TICKET_NOT_FOUND` (200) | UI: ticket detail → Close (confirmation; hidden on closed tickets) | W |

¹ filters = `category`, `location`, `plan_type`, `billing`, `country`, `city`, `cpu_type` (an unknown value → 400 `INVALID_<FIELD>`, translated generically). The client passes them through; the bot's UI does not yet expose a filter picker.

HTTP statuses handled: 200 400 401 402 403 404 405 409 422 429 500 **502**. `success` is always checked (HTTP 200 + `success:false` is an error). `error` is the machine code; `message` (Persian) is only a fallback for unknown codes in the Persian UI.

## Changes since 1.1.0 and how each was handled
| Change in 1.3.3 | Handling |
|---|---|
| Base URL `my.trusthost.co` (old `.ir` still answers) | New default in `config.py`, `.env.example`, `install.sh`, README; existing `.env` files unaffected; test for both hosts |
| Classification fields + query filters on groups/products/services | Models carry the new fields (null-tolerant); client forwards filters, unknown names rejected locally, unknown values → 400 `INVALID_<FIELD>` |
| Hourly billing (`billing: hourly`, `hourly{}`, `billingcycle: hourly`, 402 on low wallet) | Client + validation support it; products are hidden in Telegram because hourly orders charge the wallet continuously and need a dedicated confirmation flow |
| Order cycles `biennially`/`triennially`; `OUT_OF_STOCK` is 409 | Client accepts them; stock/`INVALID_BILLING_CYCLE` translated |
| Invoice pagination (`page`, `limit`), `pagination` object | `list_invoices_page`; bot fetches `limit=100`; the "20 most recent" note was corrected |
| `/invoices/details` | Single-invoice lookups no longer scan the list |
| `/wallet/topup` | New wallet top-up flow (card/USDT) |
| Renewal response redesigned (`is_existing`, urls, `status`; no `due_date`/`created`; `NOT_DUE_YET` removed; 422 promo) | `RenewResult` accepts both shapes; view no longer prints a due date; the bot's `NOT_DUE_YET` translation is kept but never produced by 1.3.3 |
| `/services/details`, `/credentials`, `/cancel`; ticket attachments | Client + tests; intentionally not wired into Telegram (see above) |
| `/tickets/close` | UI with confirmation |
| 502 `ACTION_FAILED` on power | Typed `TrustHostServerError`, translated, never auto-retried |
| `/services/action` deprecated | Not used |
| Rate limits: keys restricted to IPs have no limit | The client's conservative local limiter (50/min) is unchanged: it is safe for both key kinds |

## Places where the documentation is intentionally loose (handled defensively, see README §7)
`Product.pricing`, `Product.cycles`, `Product.setup_fees` and `Product.hourly` contents; `config_options[].sub_options[]`; `custom_fields[].fieldtype`;
`daily_traffic.items[]`; `Service.traffic`; the meaning of the invoice `balance` field (the bot keeps estimating the payable amount as `total − credit`
and lets the API's atomic `pay-credit` check be authoritative); the maximum attachment size (the client enforces a conservative local cap of 1 MB).
