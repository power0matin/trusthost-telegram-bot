"""Secret redaction helpers. Anything that may reach a log line goes through here."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_PATTERNS = [
    re.compile(r"th_sec_[A-Za-z0-9_\-]+"),
    re.compile(r"th_res_[A-Za-z0-9_\-]+"),
    re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{30,}\b"),  # Telegram bot token
]
_SENSITIVE_KEYS = {
    "rootpw", "password", "passwd", "secret", "api_secret", "api_key", "token", "authorization",
    "x-reseller-key", "x-reseller-secret", "bot_token", "telegram_bot_token",
}
_REGISTERED: set[str] = set()
MASK = "***"


def register_secret(value: str | None) -> None:
    """Remember a literal secret so it is masked wherever it appears."""
    if value and len(value) >= 6:
        _REGISTERED.add(value)


def clear_registered_secrets() -> None:
    _REGISTERED.clear()


def redact_text(text: str) -> str:
    for secret in _REGISTERED:
        if secret in text:
            text = text.replace(secret, MASK)
    for pat in _PATTERNS:
        text = pat.sub(MASK, text)
    return text


def is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return k in _SENSITIVE_KEYS or any(s in k for s in ("password", "secret", "token"))


def scrub(value: Any, _depth: int = 0) -> Any:
    """Recursively mask sensitive keys and secret-looking strings."""
    if _depth > 6:
        return MASK
    if isinstance(value, Mapping):
        return {str(k): (MASK if is_sensitive_key(str(k)) else scrub(v, _depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [scrub(v, _depth + 1) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def mask_value(value: str, keep: int = 4) -> str:
    if len(value) <= keep:
        return MASK
    return f"{MASK}{value[-keep:]}"
