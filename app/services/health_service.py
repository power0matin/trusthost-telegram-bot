from __future__ import annotations

import time
from dataclasses import dataclass

from aiogram import Bot

from app.core.formatting import now_tehran
from app.database.repository import Repository
from app.trusthost.client import TrustHostClient
from app.trusthost.exceptions import TrustHostAPIError, TrustHostError


@dataclass(slots=True)
class HealthReport:
    telegram_ok: bool
    database_ok: bool
    api_ok: bool
    api_error_code: str | None
    api_ms: int | None
    checked_at: str


class HealthService:
    def __init__(self, bot: Bot, repo: Repository, client: TrustHostClient) -> None:
        self._bot, self._repo, self._c = bot, repo, client

    async def check(self) -> HealthReport:
        """Read-only probes only (GET /wallet). Never exposes credentials."""
        try:
            await self._bot.get_me()
            tg = True
        except Exception:
            tg = False
        db = await self._repo.ping()
        api, code, ms = True, None, None
        started = time.monotonic()
        try:
            await self._c.get_wallet(force=True)
        except TrustHostAPIError as exc:
            api, code = False, exc.code
        except TrustHostError as exc:
            api, code = False, type(exc).__name__
        ms = int((time.monotonic() - started) * 1000)
        return HealthReport(tg, db, api, code, ms, now_tehran().strftime("%Y-%m-%d %H:%M:%S"))
