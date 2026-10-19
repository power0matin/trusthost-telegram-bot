"""Exception hierarchy for the TrustHost API client.

`str(exc)` is always safe to log: it contains only the machine code and HTTP status,
never response bodies or credentials.
"""
from __future__ import annotations

from typing import Any

NOT_FOUND_CODES = {"SERVICE_NOT_FOUND", "INVOICE_NOT_FOUND", "TICKET_NOT_FOUND"}


class TrustHostError(Exception):
    """Base class for every client-side failure."""


class TrustHostConnectionError(TrustHostError):
    """Network failure, timeout, DNS, TLS."""


class TrustHostProtocolError(TrustHostError):
    """The server answered with something that is not the documented JSON envelope."""


class TrustHostAPIError(TrustHostError):
    """TrustHost answered, but `success` was false or the HTTP status was an error."""

    def __init__(
        self,
        code: str,
        *,
        status: int = 200,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(f"{code} (HTTP {status})")
        self.code = code
        self.status = status
        self.api_message = message
        self.payload: dict[str, Any] = payload or {}
        self.retry_after = retry_after


class TrustHostBadRequestError(TrustHostAPIError): ...
class TrustHostAuthenticationError(TrustHostAPIError): ...
class TrustHostInsufficientCreditError(TrustHostAPIError): ...
class TrustHostForbiddenError(TrustHostAPIError): ...
class TrustHostNotFoundError(TrustHostAPIError): ...
class TrustHostConflictError(TrustHostAPIError): ...
class TrustHostServerBusyError(TrustHostConflictError): ...
class TrustHostUnprocessableError(TrustHostAPIError): ...
class TrustHostServerError(TrustHostAPIError): ...


class TrustHostRateLimitError(TrustHostAPIError):
    def __init__(self, retry_after: int = 60, *, local: bool = False, payload: dict[str, Any] | None = None) -> None:
        super().__init__("RATE_LIMITED", status=429, retry_after=retry_after, payload=payload)
        self.local = local  # True when our own limiter refused, no request was sent


_DEFAULT_CODES = {
    400: "BAD_REQUEST", 401: "UNAUTHORIZED", 402: "INSUFFICIENT_CREDIT", 403: "FORBIDDEN",
    404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 422: "UNPROCESSABLE",
    429: "RATE_LIMITED", 500: "SERVER_ERROR",
}


def build_api_error(status: int, payload: dict[str, Any], retry_after: int | None = None) -> TrustHostAPIError:
    raw_code = payload.get("error")
    code = str(raw_code) if raw_code else _DEFAULT_CODES.get(status, "UNKNOWN_ERROR" if status < 500 else "SERVER_ERROR")
    message = payload.get("message") if isinstance(payload.get("message"), str) else None
    kw: dict[str, Any] = {"status": status, "message": message, "payload": payload, "retry_after": retry_after}

    if code == "BUSY":
        return TrustHostServerBusyError(code, **kw)
    if status == 401 or code == "UNAUTHORIZED":
        return TrustHostAuthenticationError(code, **kw)
    if status == 402 or code == "INSUFFICIENT_CREDIT":
        return TrustHostInsufficientCreditError(code, **kw)
    if status == 403 or code in {"FORBIDDEN", "API_DISABLED"}:
        return TrustHostForbiddenError(code, **kw)
    if status == 404 or code in NOT_FOUND_CODES:
        return TrustHostNotFoundError(code, **kw)
    if status == 429 or code == "RATE_LIMITED":
        return TrustHostRateLimitError(retry_after or 60, payload=payload)
    if status == 409:
        return TrustHostConflictError(code, **kw)
    if status == 422:
        return TrustHostUnprocessableError(code, **kw)
    if status >= 500:
        return TrustHostServerError(code, **kw)
    if status == 400:
        return TrustHostBadRequestError(code, **kw)
    return TrustHostAPIError(code, **kw)
