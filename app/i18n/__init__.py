"""Localisation. Every user-facing string lives in fa.json / en.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.constants import SUPPORTED_LANGUAGES

_DIR = Path(__file__).parent
CATALOGS: dict[str, dict[str, str]] = {
    lang: json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8")) for lang in SUPPORTED_LANGUAGES
}


def has_key(lang: str, key: str) -> bool:
    return key in CATALOGS.get(lang, {})


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Translate `key`. Falls back to English, then to the key itself (visible in tests, never crashes)."""
    text = CATALOGS.get(lang, {}).get(key) or CATALOGS["en"].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
