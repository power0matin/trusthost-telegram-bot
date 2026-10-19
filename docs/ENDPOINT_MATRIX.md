# TrustHost Customer API 1.1.0 → Telegram feature matrix

Source of truth: the official API documentation. Every documented route is mapped; nothing else is called.

Risk: **R** = read-only · **W** = state change (no money) · **$** = creates an invoice · **$$** = spends money / irreversible · **!** = can interrupt a running server

| # | Method & route | Parameters | Key response fields | Documented errors | Telegram feature | Risk |
|---|---|---|---|---|---|---|
| 1 | GET `/catalog/groups` | – | `groups[id,name,headline,tagline]` | 401 429 | Order → product groups (cache 5 min) | R |
| 2 | GET `/catalog/products` | `group_id`, `product_id`, `promocode`(needs product_id), `billingcycle` | `products[id,group_id,group_name,name,type,paytype,description,pricing]`, `promo` | 401 429 · promo codes | Order → products / product detail / cycle list | R |
| 3 | GET `/catalog/options` | `product_id`* | `config_options[id,name,type,sub_options[]]`, `custom_fields[id,fieldname,fieldtype,description,fieldoptions]` | 400 401 | Order → dynamic configuration steps | R |
| 4 | POST `/orders/validate-promo` | `product_id`*, `promocode`*, `billingcycle` | `valid, code, type, value, original_amount, discount_amount, final_amount, message, error` | always 200 – check `valid`; 401 | Order → promo preview | R |
| 5 | POST `/orders/create` | `product_id`*, `billingcycle`, `promocode`, `payment_method`(`usdt`), `configoptions`, `customfields`, `domain`, `hostname`, `rootpw` | `order_id, invoice_id, total, status, payment_url, direct_payment_url, discount_amount, is_duplicate` | 400 (`PRODUCT_NOT_FOUND`, `OUT_OF_STOCK`, `ORDER_CREATION_FAILED`, promo codes) 401 | Order → confirm → invoice | $ |
| 6 | GET `/invoices` | `status` (Unpaid/Paid/Cancelled/Refunded) | `invoices[…]` (**20 most recent only**) | 401 | Invoices (filters, pagination of the ≤20 rows) | R |
| 7 | GET `/invoices/pay-url` | `invoice_id`*, `gateway`(`usdt`) | `direct_payment_url, amount, gateway` | 400 401 404 · `ALREADY_PAID` (200, success:false) | "Pay online" / "Pay with USDT" URL buttons | R |
| 8 | POST `/invoices/pay-credit` | `invoice_id`* | `amount_paid, status, wallet_balance` | 400 401 **402** 404 409 (`INVOICE_NOT_UNPAID`,`NOTHING_DUE`,`BUSY`) | Wallet payment with confirm screen | $$ |
| 9 | GET `/wallet` | – | `balance, add_funds_url` | 401 | Wallet screen / dashboard / "Add funds" URL button | R |
| 10 | GET `/services` | – | `services[id,product_name,servertype,domain,dedicatedip,assignedips,amount,billingcycle,nextduedate,status]` | 401 | My Servers, dashboard counters | R |
| 11 | POST `/services/renew` | `service_id`*, `promocode` | `invoice_id, total, due_date, created, promo{code,discount}` | 400 401 404 409 (`NOT_DUE_YET`+dates, `NOT_RENEWABLE`, `SERVICE_NOT_ACTIVE`, `PROMO_ALREADY_APPLIED`, `INVOICE_NOT_UNPAID`) 422 (promo) | Renew flow | $ |
| 12 | GET `/services/status` | `service_id`* | `service_status, power_state, cpu, ram_mb, disk_gb, ip` | 400 (`MISSING_SERVICE_ID`,`NOT_SUPPORTED`) 401 404 409 (`SERVICE_NOT_ACTIVE`,`VM_NOT_READY`,`BUSY`) | Server → Status | R |
| 13 | POST `/services/power` | `service_id`*, `action`* (`on/off/shutdown/reboot`) | `message` (async!) | 400 (`INVALID_ACTION`,…) 401 404 409 | Server → Power (+ confirm, + status polling) | ! |
| 14 | GET `/services/traffic` | `service_id`* | `used_gb, download_gb, upload_gb, limit_gb, unlimited, remaining_gb, percent_used, period_*, data_status, last_synced_at` | 400 401 404 | Server → Traffic | R |
| 15 | GET `/services/usage` | `service_id`*, `days` 1-90 (default 30) | `resources{…}, traffic{…}, daily_traffic{unit,from,to,items[]}` | 400 (`INVALID_DAYS`,…) 401 404 409 | Server → Usage (+ main-menu "Usage") | R |
| 16 | GET `/services/traffic-topup/quote` | `service_id`*, `promocode` | `currency, options[gb,price,discount,total], promo{valid,code,error,message}` | 400 401 404 | Top-up: dynamic size list | R |
| 17 | POST `/services/traffic-topup` | `service_id`*, `gb`*, `promocode` | `invoice_id, price, discount, total, status` | 400 (`TRAFFIC_TIER_UNAVAILABLE`) 401 404 409 (`SERVICE_NOT_ACTIVE`,`TOPUP_NO_PERIOD`) 422 (promo) | Top-up confirm → invoice | $ |
| 18 | GET `/tickets` | – | `tickets[id,tid,department,subject,status,priority,lastreply,date]` (**20 most recent**) | 401 | Support → My tickets; notification poller | R |
| 19 | GET `/tickets/departments` | – | `departments[id,name,description]` | 401 | New ticket → department | R |
| 20 | GET `/tickets/details` | `ticket_id`* (not `tid`) | `ticket{…}, replies[id,admin,name,message,date]` | 401 · `TICKET_NOT_FOUND` (200, success:false) | Ticket detail | R |
| 21 | POST `/tickets/create` | `subject`*, `message`*, `dept_id`, `priority`, `service_id` | `ticket_id, tid` | 400 (`EMPTY_FIELDS`,`TICKET_CREATE_FAILED`) 401 | New ticket flow | W |
| 22 | POST `/tickets/reply` | `ticket_id`*, `message`* | `message` | 400 (`TICKET_NOT_FOUND`,`TICKET_REPLY_FAILED`) 401 | Ticket reply | W |

HTTP statuses in the docs: 200 400 401 402 403 404 405 409 **422** 429 500. All are handled (422 appears in the renew / top-up routes).
Global rule: always check `success`; `error` is the machine code, `message` is a Persian human message.

## Not in the API → not in the bot
There is no endpoint for: wallet deposit processing, OS reinstall, root-password change, IP change, resize, DNS, profile editing, cancellation, fetching a single invoice, webhooks. The bot shows *"This feature is not available through the TrustHost Customer API"* and never fakes them. (Single-invoice lookups are done by finding the invoice in the 20-row `/invoices` list; ticket/service/invoice notifications are polling-based because there are no webhooks.)

## Places where the documentation is intentionally loose (handled defensively, see README "Documentation gaps")
* `Product.pricing` – shape not specified → parsed defensively; cycles fall back to the four documented cycle names.
* `config_options[].type` and `sub_options[]` fields beyond `id` – not specified → WHMCS convention (type 4 = quantity; no sub-options ⇒ quantity) + label fallbacks.
* `custom_fields[].fieldtype/fieldoptions` – only `text` appears → text/textarea/password/link as text, `dropdown` from comma-separated `fieldoptions`, `tickbox` as yes/no.
* `daily_traffic.items[]` – rendered as `{}` in the docs → date / inbound / outbound keys located by several aliases; shows a notice if unrecognised.
* `INSUFFICIENT_CREDIT` – "returned with the amounts" without field names → the bot computes amounts itself from `/wallet` and `/invoices` before asking for confirmation.
