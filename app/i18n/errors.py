"""Centralised translation of TrustHost / client errors into friendly localized text."""
from __future__ import annotations

import html
from typing import Any

from app.core.formatting import Fmt
from app.i18n import has_key, t
from app.trusthost.exceptions import (
    TrustHostAPIError, TrustHostAuthenticationError, TrustHostConnectionError, TrustHostForbiddenError,
    TrustHostProtocolError, TrustHostRateLimitError, TrustHostServerError,
)


def translate_trusthost_error(code: str, lang: str, **ctx: Any) -> str:
    """Translate an API error code. Unknown codes yield a generic message that includes the code."""
    key = f"err.{code}"
    f = Fmt(lang)
    safe = {k: html.escape(str(v)) for k, v in ctx.items() if v is not None}
    if "seconds" in ctx and ctx["seconds"] is not None:
        safe["seconds"] = f.int(ctx["seconds"])
    for date_key in ("next_due_date", "next_invoice_date"):
        if ctx.get(date_key):
            safe[date_key] = f.date(ctx[date_key])
    if has_key(lang, key):
        # missing placeholders fall back to a dash instead of leaking "{name}"
        for needed in ("next_due_date", "next_invoice_date", "seconds", "status"):
            safe.setdefault(needed, "—")
        return t(lang, key, **safe)
    return t(lang, "err.unknown", code=html.escape(code))


def translate_exception(exc: BaseException, lang: str) -> str:
    """Localized text for any exception raised by the TrustHost layer."""
    if isinstance(exc, TrustHostRateLimitError):
        return translate_trusthost_error("RATE_LIMITED", lang, seconds=exc.retry_after)
    if isinstance(exc, TrustHostAuthenticationError):
        return translate_trusthost_error("UNAUTHORIZED", lang)
    if isinstance(exc, TrustHostConnectionError):
        return t(lang, "err.connection")
    if isinstance(exc, TrustHostProtocolError):
        return t(lang, "err.protocol")
    if isinstance(exc, TrustHostAPIError):
        if isinstance(exc, TrustHostServerError) and exc.code in {"SERVER_ERROR", "UNKNOWN_ERROR"}:
            return t(lang, "err.server")
        payload = exc.payload or {}
        ctx = {
            "status": payload.get("service_status"),
            "next_due_date": payload.get("next_due_date"),
            "next_invoice_date": payload.get("next_invoice_date"),
        }
        text = translate_trusthost_error(exc.code, lang, **ctx)
        if not has_key(lang, f"err.{exc.code}") and lang == "fa" and exc.api_message:
            # TrustHost's own message is Persian and user-oriented – use it for unknown codes in fa.
            return t(lang, "err.generic_with_message", message=html.escape(exc.api_message))
        return text
    return t(lang, "err.generic")
