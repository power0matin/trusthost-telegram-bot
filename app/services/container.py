"""Dependency container. One TrustHost account today; `Hub` is the seam for per-user clients later."""
from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot

from app.core.config import Settings
from app.core.guard import OperationGuard
from app.database.repository import Repository
from app.services.account_service import AccountService
from app.services.audit import AuditService
from app.services.billing_service import BillingService
from app.services.catalog_service import CatalogService
from app.services.health_service import HealthService
from app.services.notification_service import NotificationService
from app.services.order_service import OrderService
from app.services.server_service import DEFAULT_POLL_DELAYS, ServerService
from app.services.ticket_service import TicketService
from app.services.traffic_service import TrafficService
from app.trusthost.client import TrustHostClient


@dataclass
class Hub:
    settings: Settings
    client: TrustHostClient
    repo: Repository
    guard: OperationGuard
    audit: AuditService
    notifier: NotificationService
    account: AccountService
    catalog: CatalogService
    orders: OrderService
    billing: BillingService
    servers: ServerService
    traffic: TrafficService
    tickets: TicketService
    health: HealthService

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.settings.admin_telegram_ids


def build_hub(settings: Settings, client: TrustHostClient, repo: Repository, bot: Bot, *,
              poll_delays: tuple[float, ...] = DEFAULT_POLL_DELAYS) -> Hub:
    guard = OperationGuard()
    audit = AuditService(repo)
    notifier = NotificationService(bot, repo, client, settings.default_language)
    return Hub(
        settings=settings, client=client, repo=repo, guard=guard, audit=audit, notifier=notifier,
        account=AccountService(client),
        catalog=CatalogService(client),
        orders=OrderService(client, guard, audit, notifier),
        billing=BillingService(client, guard, audit, notifier),
        servers=ServerService(client, guard, audit, notifier, poll_delays=poll_delays),
        traffic=TrafficService(client, guard, audit, notifier),
        tickets=TicketService(client, guard, audit, notifier),
        health=HealthService(bot, repo, client),
    )
