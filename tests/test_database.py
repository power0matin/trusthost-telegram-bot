from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

import pytest

from app.core.config import Settings
from tests.conftest import ADMIN_ID
from tests.fakes import API_KEY, API_SECRET, BOT_TOKEN


async def test_user_language_and_notification_prefs_persist(repo):
    u = await repo.get_or_create_user(5)
    assert u.language is None and u.notify_tickets and u.notify_services and u.notify_payments
    assert (await repo.set_language(5, "fa")).language == "fa"
    assert (await repo.get_or_create_user(5)).language == "fa"
    assert (await repo.set_notification_pref(5, "payments", False)).wants("payments") is False
    with pytest.raises(ValueError):
        await repo.set_notification_pref(5, "bogus", True)
    assert len(await repo.list_users()) == 1


async def test_notification_state_upsert_and_reset(repo):
    await repo.set_states(1, "tickets", {"a": "x", "b": "y"})
    await repo.set_states(1, "tickets", {"a": "z", "c": "w"})
    assert await repo.get_states(1, "tickets") == {"a": "z", "b": "y", "c": "w"}
    assert await repo.get_states(2, "tickets") == {} and await repo.get_states(1, "services") == {}
    await repo.touch_poll(1, "tickets")
    assert await repo.get_last_poll(1, "tickets") is not None
    await repo.reset_notification_state(1, "tickets")
    assert await repo.get_states(1, "tickets") == {} and await repo.get_last_poll(1, "tickets") is None


async def test_audit_log_truncates_and_orders(repo):
    await repo.add_audit(1, "A" * 100, "r", "success", "d" * 500)
    await repo.add_audit(1, "B", None, "failure", "ERR")
    rows = await repo.list_audit(1)
    assert [r.action[:1] for r in rows] == ["B", "A"] and len(rows[1].action) == 48 and len(rows[1].detail) == 255
    assert await repo.ping() is True


def test_alembic_migration_creates_schema_and_matches_models(tmp_path):
    db = tmp_path / "mig.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db}"}
    for args in (["upgrade", "head"], ["check"]):
        r = subprocess.run([sys.executable, "-m", "alembic", *args], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    tables = {row[0] for row in sqlite3.connect(db).execute("select name from sqlite_master where type='table'")}
    assert {"users", "notification_state", "poll_status", "audit_log", "alembic_version"} <= tables
    r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], env=env, capture_output=True, text=True)
    assert r.returncode == 0


# ------------------------------------------------------------------ config
def mk(**kw):  # type: ignore[no-untyped-def]
    base = dict(trusthost_api_key=API_KEY, trusthost_api_secret=API_SECRET, telegram_bot_token=BOT_TOKEN, admin_telegram_ids="1")
    base.update(kw)
    return Settings(_env_file=None, **base)


@pytest.mark.parametrize("raw,expected", [("123", [123]), ("1, 2 ,3", [1, 2, 3]), ("[4,5]", [4, 5]), ("7;8", [7, 8])])
def test_admin_ids_parsing(raw, expected):
    assert mk(admin_telegram_ids=raw).admin_telegram_ids == expected


def test_admin_ids_required_so_the_bot_is_never_open():
    with pytest.raises(Exception):
        mk(admin_telegram_ids="")


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("TRUSTHOST_API_KEY", API_KEY)
    monkeypatch.setenv("TRUSTHOST_API_SECRET", API_SECRET)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", "10,20")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("TRUSTHOST_BASE_URL", "https://my.trusthost.ir/api/v1/")
    s = Settings(_env_file=None)
    assert s.admin_telegram_ids == [10, 20] and s.database_url == "postgresql+asyncpg://u:p@h/db"
    assert s.trusthost_base_url == "https://my.trusthost.ir/api/v1" and s.trusthost_max_requests_per_minute == 50


def test_missing_credentials_fail_fast(monkeypatch):
    for k in ("TRUSTHOST_API_KEY", "TRUSTHOST_API_SECRET", "TELEGRAM_BOT_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(Exception):
        Settings(_env_file=None, admin_telegram_ids="1")
