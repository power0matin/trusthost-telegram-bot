"""Persistence API. Returns plain dataclasses, never ORM objects."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AuditLog, NotificationState, PollStatus, User, utcnow

NOTIFY_KINDS = {"tickets": "notify_tickets", "services": "notify_services", "payments": "notify_payments"}


@dataclass(slots=True)
class UserRecord:
    telegram_id: int
    language: str | None
    notify_tickets: bool = True
    notify_services: bool = True
    notify_payments: bool = True

    def wants(self, kind: str) -> bool:
        return bool(getattr(self, NOTIFY_KINDS[kind]))


@dataclass(slots=True)
class AuditRecord:
    telegram_id: int
    action: str
    resource: str | None
    result: str
    detail: str | None
    created_at: datetime


def _rec(u: User) -> UserRecord:
    return UserRecord(u.telegram_id, u.language, u.notify_tickets, u.notify_services, u.notify_payments)


class Repository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        self._lang_cache: dict[int, str | None] = {}

    # ------------------------------------------------------------- users
    async def get_or_create_user(self, telegram_id: int) -> UserRecord:
        async with self._sf() as s, s.begin():
            user = await s.get(User, telegram_id)
            if user is None:
                user = User(telegram_id=telegram_id, language=None)
                s.add(user)
                await s.flush()
            return _rec(user)

    async def set_language(self, telegram_id: int, language: str) -> UserRecord:
        async with self._sf() as s, s.begin():
            user = await s.get(User, telegram_id)
            if user is None:
                user = User(telegram_id=telegram_id, language=language)
                s.add(user)
            else:
                user.language = language
            await s.flush()
            return _rec(user)

    async def set_notification_pref(self, telegram_id: int, kind: str, value: bool) -> UserRecord:
        if kind not in NOTIFY_KINDS:
            raise ValueError(f"unknown notification kind: {kind}")
        async with self._sf() as s, s.begin():
            user = await s.get(User, telegram_id)
            if user is None:
                user = User(telegram_id=telegram_id)
                s.add(user)
            setattr(user, NOTIFY_KINDS[kind], value)
            await s.flush()
            return _rec(user)

    async def list_users(self) -> list[UserRecord]:
        async with self._sf() as s:
            return [_rec(u) for u in (await s.scalars(select(User))).all()]

    # ------------------------------------------------------------- notification state
    async def get_states(self, telegram_id: int, kind: str) -> dict[str, str]:
        async with self._sf() as s:
            rows = await s.scalars(select(NotificationState).where(
                NotificationState.telegram_id == telegram_id, NotificationState.kind == kind))
            return {r.resource_id: r.state for r in rows}

    async def set_states(self, telegram_id: int, kind: str, states: dict[str, str]) -> None:
        if not states:
            return
        async with self._sf() as s, s.begin():
            rows = await s.scalars(select(NotificationState).where(
                NotificationState.telegram_id == telegram_id, NotificationState.kind == kind,
                NotificationState.resource_id.in_(list(states))))
            existing = {r.resource_id: r for r in rows}
            for rid, state in states.items():
                if rid in existing:
                    existing[rid].state = state[:255]
                    existing[rid].updated_at = utcnow()
                else:
                    s.add(NotificationState(telegram_id=telegram_id, kind=kind, resource_id=rid, state=state[:255]))

    async def get_last_poll(self, telegram_id: int, kind: str) -> datetime | None:
        async with self._sf() as s:
            row = await s.get(PollStatus, (telegram_id, kind))
            return row.last_checked_at if row else None

    async def touch_poll(self, telegram_id: int, kind: str) -> None:
        async with self._sf() as s, s.begin():
            row = await s.get(PollStatus, (telegram_id, kind))
            if row is None:
                s.add(PollStatus(telegram_id=telegram_id, kind=kind, last_checked_at=utcnow()))
            else:
                row.last_checked_at = utcnow()

    async def reset_notification_state(self, telegram_id: int, kind: str) -> None:
        async with self._sf() as s, s.begin():
            await s.execute(delete(NotificationState).where(
                NotificationState.telegram_id == telegram_id, NotificationState.kind == kind))
            await s.execute(delete(PollStatus).where(
                PollStatus.telegram_id == telegram_id, PollStatus.kind == kind))

    # ------------------------------------------------------------- audit
    async def add_audit(self, telegram_id: int, action: str, resource: str | None, result: str,
                        detail: str | None = None) -> None:
        async with self._sf() as s, s.begin():
            s.add(AuditLog(telegram_id=telegram_id, action=action[:48],
                           resource=resource[:64] if resource else None, result=result[:16],
                           detail=detail[:255] if detail else None))

    async def list_audit(self, telegram_id: int | None = None, limit: int = 20) -> list[AuditRecord]:
        async with self._sf() as s:
            q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
            if telegram_id is not None:
                q = q.where(AuditLog.telegram_id == telegram_id)
            return [AuditRecord(a.telegram_id, a.action, a.resource, a.result, a.detail, a.created_at)
                    for a in (await s.scalars(q)).all()]

    # ------------------------------------------------------------- health
    async def ping(self) -> bool:
        try:
            async with self._sf() as s:
                await s.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
