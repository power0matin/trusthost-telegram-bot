from __future__ import annotations

SUPPORTED_LANGUAGES = ("fa", "en")

BILLING_CYCLES = ("monthly", "quarterly", "semiannually", "annually")
CYCLE_CODES = {"m": "monthly", "q": "quarterly", "s": "semiannually", "a": "annually"}
CYCLE_TO_CODE = {v: k for k, v in CYCLE_CODES.items()}

# Cycles accepted by POST /orders/create in API 1.3.x (the bot's cycle picker only offers BILLING_CYCLES;
# hourly products are not orderable from the bot).
ORDER_BILLING_CYCLES = BILLING_CYCLES + ("biennially", "triennially", "hourly")
GATEWAYS = ("usdt",)  # online gateway override; omit for card payment (Zarinpal)
CANCEL_TYPES = ("End of Billing Period", "Immediate")
MIN_TOPUP_AMOUNT = 10_000  # Toman, per POST /wallet/topup

POWER_ACTIONS = ("on", "off", "shutdown", "reboot")
POWER_CONFIRM_ACTIONS = ("off", "shutdown", "reboot")
POWER_EXPECTED_STATE = {"on": "POWERED_ON", "off": "POWERED_OFF", "shutdown": "POWERED_OFF"}

USAGE_DAY_CHOICES = (7, 14, 30, 60, 90)
DEFAULT_USAGE_DAYS = 30

INVOICE_FILTERS = {"u": "Unpaid", "p": "Paid", "c": "Cancelled", "r": "Refunded", "a": None}
TICKET_PRIORITIES = ("Low", "Medium", "High")
PRIORITY_CODES = {"L": "Low", "M": "Medium", "H": "High"}

TIMEZONE = "Asia/Tehran"

PAGE_SIZE = 6
LIST_PAGE_SIZE = 5

MAX_TICKET_SUBJECT = 200
MAX_TICKET_MESSAGE = 4000
MAX_PROMO_LEN = 50
MAX_HOSTNAME_LEN = 253
TELEGRAM_TEXT_LIMIT = 3900

# Cache TTLs (seconds)
TTL_CATALOG = 300
TTL_SERVICES = 30
TTL_INVOICES = 20
TTL_WALLET = 10
TTL_TICKETS = 30
TTL_DEPARTMENTS = 300
