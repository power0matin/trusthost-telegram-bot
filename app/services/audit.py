from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.core.logging import get_logger, log_event
from app.database.repository import Repository
from app.trusthost.exceptions import TrustHostError

T = TypeVar("T")
log = get_logger("audit")


class AuditService:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    async def record(self, user_id: int, action: str, resource: str | None, result: str,
                     detail: str | None = None) -> None:
        log_event(log, "audit", user=user_id, action=action, resource=resource, result=result, detail=detail)
        try:
            await self._repo.add_audit(user_id, action, resource, result, detail)
        except Exception:  # auditing must never break the operation itself
            log.exception("audit_write_failed")

    async def run(self, user_id: int, action: str, resource: str | None,
                  fn: Callable[[], Awaitable[T]]) -> T:
        """Execute `fn` and audit success/failure (error code only – never payloads)."""
        try:
            result = await fn()
        except TrustHostError as exc:
            await self.record(user_id, action, resource, "failure", getattr(exc, "code", type(exc).__name__))
            raise
        await self.record(user_id, action, resource, "success")
        return result
