from __future__ import annotations

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.setup import build_dispatcher
from app.core.config import Settings
from app.core.security import clear_registered_secrets
from app.database.models import Base
from app.database.repository import Repository
from app.database.session import create_engine, create_session_factory
from app.services.container import build_hub
from app.trusthost.client import TrustHostClient
from tests.fakes import API_KEY, API_SECRET, BOT_TOKEN, FakeSession, FakeTrustHost, Telegram, make_transport

ADMIN_ID = 111


async def _no_sleep(_: float) -> None:
    return None


def make_settings(db_url: str, **over) -> Settings:  # type: ignore[no-untyped-def]
    base = dict(trusthost_api_key=API_KEY, trusthost_api_secret=API_SECRET, telegram_bot_token=BOT_TOKEN,
                admin_telegram_ids=str(ADMIN_ID), database_url=db_url, notification_poll_minutes=5)
    base.update(over)
    return Settings(_env_file=None, **base)


@pytest.fixture(autouse=True)
def _clean_secrets():
    yield
    clear_registered_secrets()


@pytest_asyncio.fixture
async def repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    r = Repository(create_session_factory(engine))
    r.db_path = f"{tmp_path}/test.db"  # type: ignore[attr-defined]
    yield r
    await engine.dispose()


@pytest.fixture
def fake() -> FakeTrustHost:
    return FakeTrustHost()


@pytest_asyncio.fixture
async def client(fake):
    c = TrustHostClient("https://my.trusthost.ir/api/v1", API_KEY, API_SECRET, transport=make_transport(fake),
                        sleep=_no_sleep, max_requests_per_minute=10_000)
    yield c
    await c.aclose()


@pytest_asyncio.fixture
async def app(repo, client, fake):
    """Full application: dispatcher + services over the fake API and a fake Telegram transport."""
    session = FakeSession()
    bot = Bot(BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    settings = make_settings(f"sqlite+aiosqlite:///{repo.db_path}")
    hub = build_hub(settings, client, repo, bot, poll_delays=(0.0, 0.0, 0.0))
    dp = build_dispatcher(hub)
    tg = Telegram(dp, bot, session, user_id=ADMIN_ID)

    class App:
        pass

    a = App()
    a.hub, a.dp, a.bot, a.tg, a.fake, a.session, a.repo = hub, dp, bot, tg, fake, session, repo  # type: ignore[attr-defined]
    yield a


@pytest_asyncio.fixture
async def en(app):
    await app.repo.set_language(ADMIN_ID, "en")
    return app


@pytest_asyncio.fixture
async def fa(app):
    await app.repo.set_language(ADMIN_ID, "fa")
    return app
