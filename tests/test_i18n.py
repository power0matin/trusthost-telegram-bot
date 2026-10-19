from __future__ import annotations

import pathlib
import re

import pytest

from app.core.formatting import Fmt, fit_text, progress_bar, truncate
from app.i18n import CATALOGS, t
from app.i18n.errors import translate_exception, translate_trusthost_error
from app.trusthost.exceptions import (
    TrustHostAuthenticationError, TrustHostConnectionError, TrustHostRateLimitError, TrustHostServerError,
    build_api_error,
)

# Every error code that appears in the TrustHost documentation (+ client-side ones).
DOC_ERROR_CODES = """UNAUTHORIZED INSUFFICIENT_CREDIT FORBIDDEN API_DISABLED RATE_LIMITED MISSING_SERVICE_ID NOT_SUPPORTED INVALID_ACTION
INVALID_DAYS SERVICE_NOT_FOUND INVOICE_NOT_FOUND TICKET_NOT_FOUND PRODUCT_NOT_FOUND SERVICE_NOT_ACTIVE VM_NOT_READY BUSY NOT_DUE_YET
NOT_RENEWABLE INVOICE_NOT_UNPAID NOTHING_DUE ALREADY_PAID OUT_OF_STOCK ORDER_CREATION_FAILED TRAFFIC_TIER_UNAVAILABLE TOPUP_NO_PERIOD
EMPTY_FIELDS TICKET_CREATE_FAILED TICKET_REPLY_FAILED EMPTY_PROMO PROMO_NOT_FOUND PROMO_NOT_STARTED PROMO_EXPIRED PROMO_MAX_USES_REACHED
PROMO_PRODUCT_MISMATCH PROMO_CYCLE_MISMATCH PROMO_NEW_SIGNUPS_ONLY PROMO_EXISTING_CLIENT_ONLY PROMO_ALREADY_USED PROMO_TRAFFIC_ONLY
PROMO_NOT_APPLICABLE PROMO_ALREADY_APPLIED PROMO_INVALID PROMO_USED_UP""".split()


def placeholders(s: str) -> list[str]:
    return sorted(re.findall(r"\{(\w+)\}", s))


def test_catalogs_have_identical_keys_and_placeholders():
    en, fa = CATALOGS["en"], CATALOGS["fa"]
    assert set(en) == set(fa), (set(en) ^ set(fa))
    for k in en:
        assert placeholders(en[k]) == placeholders(fa[k]), k
        assert en[k].strip() and fa[k].strip(), k


def test_persian_strings_are_really_persian():
    fa = CATALOGS["fa"]
    skip_prefixes = ("lang.", "cmd.")  # lang.choose is bilingual by design
    for k, v in fa.items():
        if k.startswith(skip_prefixes) or k in {"order.gw_usdt", "err.generic_with_message", "btn.pay_usdt"}:
            continue
        assert re.search(r"[\u0600-\u06FF]", v), f"{k} has no Persian: {v!r}"


def _static_keys() -> set[str]:
    pats = [re.compile(r"""\bt\(\s*[\w.]+\s*,\s*["']([\w.]+)["']"""),
            re.compile(r"""\bline\(\s*lang\s*,\s*["']([\w.]+)["']"""),
            re.compile(r"""["'](order\.prompt_\w+)["']""")]
    keys: set[str] = set()
    for p in pathlib.Path("app").rglob("*.py"):
        text = p.read_text()
        for pat in pats:
            keys |= set(pat.findall(text))
    return keys


def test_every_key_referenced_in_code_exists():
    missing = [k for k in _static_keys() if k not in CATALOGS["en"]]
    assert not missing, missing


def test_dynamic_key_families_exist():
    en = CATALOGS["en"]
    want = []
    want += [f"menu.{k}" for k in ("title", "servers", "order", "invoices", "wallet", "usage", "support", "settings")]
    want += [f"cycle.{k}" for k in ("monthly", "quarterly", "semiannually", "annually")]
    want += [f"power.{p}_{a}" for p in ("btn", "act") for a in ("on", "off", "shutdown", "reboot")]
    want += [f"power.confirm_{a}" for a in ("off", "shutdown", "reboot")] + [f"power.yes_{a}" for a in ("off", "shutdown", "reboot")]
    want += [f"inv.filter_{k}" for k in ("unpaid", "paid", "cancelled", "refunded", "all")]
    want += [f"inv.{k}" for k in ("unpaid", "paid", "cancelled", "refunded")]
    want += [f"prio.{k}" for k in ("low", "medium", "high")]
    want += [f"pow.{k}" for k in ("poweredon", "poweredoff", "suspended", "unknown")]
    want += [f"set.notify_{k}" for k in ("tickets", "services", "payments")]
    want += [f"cmd.{k}" for k in ("start", "menu", "servers", "orders", "invoices", "wallet", "usage", "support", "settings", "help", "cancel")]
    want += ["loading", "processing", "cancelled"] + [f"val.{k}" for k in ("promo", "hostname", "domain", "password", "quantity", "custom", "subject", "message", "priority", "action", "days")]
    want += [f"data.{k}" for k in ("ok", "pending", "unavailable")] + [f"svc.{k}" for k in ("active", "suspended", "pending")]
    want += [f"tkt.{k}" for k in ("open", "answered", "customerreply", "closed")]
    assert not [k for k in want if k not in en], [k for k in want if k not in en]


@pytest.mark.parametrize("code", DOC_ERROR_CODES)
@pytest.mark.parametrize("lang", ["fa", "en"])
def test_every_documented_error_code_is_translated_never_raw(code, lang):
    text = translate_trusthost_error(code, lang, status="Suspended", seconds=5, next_due_date="2026-11-02", next_invoice_date="2026-10-19")
    assert code not in text and "{" not in text and "err." not in text
    assert text != t(lang, "err.unknown", code=code)


def test_error_translation_specifics_match_the_spec():
    assert "❌ " + translate_trusthost_error("UNAUTHORIZED", "fa") == "❌ احراز هویت با TrustHost انجام نشد."
    assert "❌ " + translate_trusthost_error("UNAUTHORIZED", "en") == "❌ TrustHost authentication failed."
    fa = translate_trusthost_error("NOT_DUE_YET", "fa", next_due_date="2026-11-02", next_invoice_date="2026-10-19")
    assert "۲۰۲۶-۱۰-۱۹" in fa and "۲۰۲۶-۱۱-۰۲" in fa
    assert "۳۷" in translate_trusthost_error("RATE_LIMITED", "fa", seconds=37)
    assert "Suspended" in translate_trusthost_error("SERVICE_NOT_ACTIVE", "en", status="Suspended")
    unknown = translate_trusthost_error("SOMETHING_NEW", "en")
    assert "SOMETHING_NEW" in unknown and "{" not in unknown


def test_translate_exception_covers_all_exception_types():
    assert "37" in translate_exception(TrustHostRateLimitError(37), "en")
    assert translate_exception(TrustHostAuthenticationError("UNAUTHORIZED", status=401), "en") == "TrustHost authentication failed."
    assert "could not be reached" in translate_exception(TrustHostConnectionError("x"), "en")
    assert "temporary error" in translate_exception(build_api_error(500, {}), "en")
    assert "کد: WEIRD" in translate_exception(build_api_error(400, {"error": "WEIRD"}), "fa") or "WEIRD" in translate_exception(build_api_error(400, {"error": "WEIRD", "message": "پیام سرور"}), "fa")
    # fa falls back to TrustHost's own Persian message for codes the bot does not know
    assert "پیام سرور" in translate_exception(build_api_error(400, {"error": "WEIRD", "message": "پیام سرور"}), "fa")
    assert "<script>" not in translate_exception(build_api_error(400, {"error": "WEIRD", "message": "<script>"}), "fa")
    assert "Something went wrong" in translate_exception(RuntimeError("x"), "en")


def test_t_fallbacks():
    assert t("en", "nope.missing") == "nope.missing"
    assert t("xx", "btn.back") == t("en", "btn.back")
    assert t("en", "val.subject") == "⚠️ The subject must be 1–{max} characters."   # missing kwarg: no crash


# ------------------------------------------------------------------ formatting
def test_money_dates_numbers():
    en, fa = Fmt("en"), Fmt("fa")
    assert en.money(1350000) == "1,350,000 Toman" and fa.money(1350000) == "۱٬۳۵۰٬۰۰۰ تومان"
    assert en.money("1350000.00") == "1,350,000 Toman" and en.money(None) == "—"
    assert en.num(412.370) == "412.37" and fa.num(412.37) == "۴۱۲٫۳۷" and en.num(1000.0) == "1,000"
    assert en.dt("2026-10-05 17:24:09") == "2026-10-05 17:24" and fa.dt("2026-10-05 17:24:09") == "۲۰۲۶-۱۰-۰۵ ۱۷:۲۴"
    assert en.date("2026-10-21") == "2026-10-21" and en.dt(None) == "—" and en.dt("garbage") == "garbage"
    assert en.ram(8192) == "8 GB" and en.ram(512) == "512 MB" and en.pct(41.2) == "41.2%" and fa.pct(41.2) == "۴۱٫۲٪"
    assert en.duration(864000) == "10d 0h 0m" and "۱۰ روز" in fa.duration(864000)
    assert len(Fmt("en").now()) == 16


def test_progress_bar_and_text_helpers():
    assert progress_bar(0) == "░" * 10 and progress_bar(100) == "▓" * 10 and progress_bar(41.2) == "▓▓▓▓░░░░░░"
    assert progress_bar(250) == "▓" * 10 and progress_bar(None) == "░" * 10
    assert truncate("x" * 50, 10).endswith("…") and len(truncate("x" * 50, 10)) == 10
    assert fit_text(["a" * 30] * 10, 100).endswith("…") and len(fit_text(["a" * 30] * 10, 100)) <= 100
