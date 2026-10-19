from __future__ import annotations

from app.core.constants import TICKET_PRIORITIES
from app.core.guard import OperationGuard
from app.services import validators
from app.services.audit import AuditService
from app.services.notification_service import NotificationService
from app.trusthost.client import TrustHostClient
from app.trusthost.models import CreateTicketResult, Department, Ticket, TicketDetail


class TicketService:
    def __init__(self, client: TrustHostClient, guard: OperationGuard, audit: AuditService,
                 notifier: NotificationService) -> None:
        self._c, self._guard, self._audit, self._notifier = client, guard, audit, notifier

    async def tickets(self, *, force: bool = False) -> list[Ticket]:
        """Only the 20 most recent tickets are exposed by the API."""
        return await self._c.list_tickets(force=force)

    async def departments(self) -> list[Department]:
        return await self._c.list_departments()

    async def detail(self, ticket_id: int) -> TicketDetail:
        return await self._c.get_ticket(ticket_id)

    async def create(self, user_id: int, *, dept_id: int, subject: str, message: str,
                     priority: str = "Medium", service_id: int | None = None) -> CreateTicketResult:
        subject = validators.ticket_subject(subject)
        message = validators.ticket_message(message)
        if priority not in TICKET_PRIORITIES:
            raise validators.InputError("val.priority")
        async with self._guard.acquire(f"ticket_create:{user_id}"):
            result = await self._audit.run(
                user_id, "CREATE_TICKET", f"dept={dept_id}",
                lambda: self._c.create_ticket(subject, message, dept_id=dept_id, priority=priority,
                                              service_id=service_id))
            await self._notifier.sync_ticket(user_id, result.ticket_id)
            return result

    async def reply(self, user_id: int, ticket_id: int, message: str) -> None:
        message = validators.ticket_message(message)
        async with self._guard.acquire(f"ticket_reply:{ticket_id}"):
            await self._audit.run(user_id, "REPLY_TICKET", f"ticket={ticket_id}",
                                  lambda: self._c.reply_ticket(ticket_id, message))
            await self._notifier.sync_ticket(user_id, ticket_id)
