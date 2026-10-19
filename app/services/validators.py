"""Local input validation. Only rules that are universally true – API-defined values stay open."""
from __future__ import annotations

import re

from app.core.constants import MAX_PROMO_LEN, MAX_TICKET_MESSAGE, MAX_TICKET_SUBJECT


class InputError(ValueError):
    """Invalid user input. `key` is an i18n key under `val.*`."""

    def __init__(self, key: str, **ctx: object) -> None:
        super().__init__(key)
        self.key = key
        self.ctx = ctx


_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
_PROMO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def promo_code(value: str) -> str:
    v = value.strip()
    if not v or len(v) > MAX_PROMO_LEN or not _PROMO.match(v):
        raise InputError("val.promo")
    return v


def hostname(value: str) -> str:
    v = value.strip().rstrip(".").lower()
    if not v or len(v) > 253 or not all(_LABEL.match(p) for p in v.split(".")):
        raise InputError("val.hostname")
    return v


def domain(value: str) -> str:
    v = hostname(value)
    if "." not in v:
        raise InputError("val.domain")
    return v


def root_password(value: str) -> str:
    # Do not strip: whitespace may be part of the password. Never logged or stored.
    if len(value) < 8 or len(value) > 128 or value != value.strip() or "\n" in value:
        raise InputError("val.password")
    return value


def quantity(value: str, maximum: int = 100000) -> int:
    v = value.strip()
    if not v.isdigit() or int(v) > maximum:
        raise InputError("val.quantity")
    return int(v)


def custom_text(value: str) -> str:
    v = value.strip()
    if not v or len(v) > 1000:
        raise InputError("val.custom")
    return v


def ticket_subject(value: str) -> str:
    v = " ".join(value.split())
    if not v or len(v) > MAX_TICKET_SUBJECT:
        raise InputError("val.subject", max=MAX_TICKET_SUBJECT)
    return v


def ticket_message(value: str) -> str:
    v = value.strip()
    if not v or len(v) > MAX_TICKET_MESSAGE:
        raise InputError("val.message", max=MAX_TICKET_MESSAGE)
    return v
