"""Entry point: `python -m app.main`."""
from __future__ import annotations

import asyncio
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import ValidationError

from app.bot.setup import build_dispatcher, set_bot_commands
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger, log_event
from app.core.security import register_secret
from app.database.repository import Repository
from app.database.session import create_engine, create_session_factory
from app.services.container import build_hub
from app.trusthost.client import TrustHostClient
from app.trusthost.exceptions import TrustHostError

log = get_logger("main")


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    token = settings.telegram_bot_token.get_secret_value()
    for secret in (token, settings.trusthost_api_key.get_secret_value(), settings.trusthost_api_secret.get_secret_value()):
        register_secret(secret)

    engine = create_engine(settings.database_url)
    repo = Repository(create_session_factory(engine))
    client = TrustHostClient(
        settings.trusthost_base_url,
        settings.trusthost_api_key.get_secret_value(),
        settings.trusthost_api_secret.get_secret_value(),
        timeout=settings.trusthost_timeout_seconds,
        max_requests_per_minute=settings.trusthost_max_requests_per_minute,
    )
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    hub = build_hub(settings, client, repo, bot)
    dp = build_dispatcher(hub)

    # Safe, read-only startup probe (GET /wallet). The bot starts even if TrustHost is down.
    try:
        await client.get_wallet(force=True)
        log_event(log, "startup_trusthost_ok")
    except TrustHostError as exc:
        log_event(log, "startup_trusthost_failed", level=40, error=getattr(exc, "code", type(exc).__name__))
    if not await repo.ping():
        log.error("startup_database_unreachable")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(hub.notifier.run_once, "interval", minutes=settings.notification_poll_minutes,
                      max_instances=1, coalesce=True, id="notifications")
    scheduler.start()
    try:
        await set_bot_commands(bot)
        log_event(log, "bot_starting", admins=len(settings.admin_telegram_ids))
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await client.aclose()
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass
    except ValidationError as exc:  # list field names only – input values could contain secrets
        fields = ", ".join(sorted({str(e["loc"][0]).upper() for e in exc.errors() if e["loc"]}))
        print(f"Configuration error – check these environment variables: {fields}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # never print secrets
        print(f"Fatal: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
