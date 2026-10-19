"""Centralised number / money / date formatting for both languages."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.constants import TIMEZONE

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
DASH = "—"


def to_fa_digits(text: str) -> str:
    return text.translate(_FA_DIGITS)


def now_tehran() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def progress_bar(percent: float | None, width: int = 10) -> str:
    if percent is None or (isinstance(percent, float) and math.isnan(percent)):
        return "░" * width
    p = max(0.0, min(100.0, float(percent)))
    filled = int(round(p / 100 * width))
    return "▓" * filled + "░" * (width - filled)


def parse_api_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip()[: 19 if fmt.endswith("%S") else 10], fmt)
        except ValueError:
            continue
    return None


class Fmt:
    """Language-aware formatter. `Fmt('fa').money(1350000)` -> '۱٬۳۵۰٬۰۰۰ تومان'."""

    def __init__(self, lang: str) -> None:
        self.lang = lang if lang in ("fa", "en") else "en"

    def digits(self, text: str) -> str:
        return to_fa_digits(text) if self.lang == "fa" else text

    def int(self, value: Any) -> str:
        if value is None:
            return DASH
        try:
            text = f"{int(round(float(value))):,}"
        except (TypeError, ValueError):
            return DASH
        if self.lang == "fa":
            return to_fa_digits(text.replace(",", "٬"))
        return text

    def num(self, value: Any, decimals: int = 2) -> str:
        if value is None:
            return DASH
        try:
            f = float(value)
        except (TypeError, ValueError):
            return DASH
        text = f"{f:,.{decimals}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        if self.lang == "fa":
            text = text.replace(",", "٬").replace(".", "٫")
            return to_fa_digits(text)
        return text

    def money(self, value: Any) -> str:
        if value is None:
            return DASH
        unit = "تومان" if self.lang == "fa" else "Toman"
        return f"{self.int(value)} {unit}"

    def pct(self, value: Any) -> str:
        if value is None:
            return DASH
        return self.num(value, 1) + ("٪" if self.lang == "fa" else "%")

    def gb(self, value: Any, unit: str = "GiB") -> str:
        if value is None:
            return DASH
        return f"{self.num(value, 2)} {unit}"

    def ram(self, mb: Any) -> str:
        if mb is None:
            return DASH
        mb = float(mb)
        if mb >= 1024:
            return f"{self.num(mb / 1024, 2)} GB"
        return f"{self.num(mb, 0)} MB"

    def dt(self, value: Any) -> str:
        parsed = parse_api_datetime(value)
        if parsed is None:
            return self.digits(str(value)) if value else DASH
        has_time = isinstance(value, str) and len(value.strip()) > 10
        return self.digits(parsed.strftime("%Y-%m-%d %H:%M" if has_time else "%Y-%m-%d"))

    def date(self, value: Any) -> str:
        parsed = parse_api_datetime(value)
        if parsed is None:
            return self.digits(str(value)) if value else DASH
        return self.digits(parsed.strftime("%Y-%m-%d"))

    def now(self) -> str:
        return self.digits(now_tehran().strftime("%Y-%m-%d %H:%M"))

    def duration(self, seconds: Any) -> str:
        if seconds is None:
            return DASH
        s = int(seconds)
        d, rem = divmod(s, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        if self.lang == "fa":
            parts = []
            if d:
                parts.append(f"{d} روز")
            if h or d:
                parts.append(f"{h} ساعت")
            parts.append(f"{m} دقیقه")
            return to_fa_digits(" و ".join(parts))
        parts = []
        if d:
            parts.append(f"{d}d")
        if h or d:
            parts.append(f"{h}h")
        parts.append(f"{m}m")
        return " ".join(parts)


def fit_text(parts: list[str], limit: int) -> str:
    """Join parts with newlines, truncating the tail if Telegram's limit would be exceeded."""
    out, size = [], 0
    for p in parts:
        if size + len(p) + 1 > limit:
            out.append("…")
            break
        out.append(p)
        size += len(p) + 1
    return "\n".join(out)


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
