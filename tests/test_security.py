from __future__ import annotations

import io
import json
import logging
import pathlib

import pytest
from aiogram.types import InlineKeyboardMarkup

from app.bot.callbacks import Cat, Menu, Srv
from app.core import logging as applog
from app.core.security import MASK, clear_registered_secrets, mask_value, redact_text, register_secret, scrub
from tests.conftest import ADMIN_ID, make_settings
from tests.fakes import API_KEY, API_SECRET, BOT_TOKEN, err

PASSWORD = "S3cretPass!"


@pytest.fixture
def captured_logs():
    """Attach the production JSON formatter + redaction filter to an in-memory stream."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(applog.RedactingFilter())
    handler.setFormatter(applog.JsonFormatter())
    root = logging.getLogger()
    old_level, old_handlers = root.level, root.handlers[:]
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG)
    yield stream
    root.handlers[:] = old_handlers
    root.setLevel(old_level)


def assert_clean(text: str) -> None:
    for secret in (API_KEY, API_SECRET, BOT_TOKEN, PASSWORD, "TESTSECRET0123456789"):
        assert secret not in text, f"secret leaked: {secret[:8]}…"


# ------------------------------------------------------------------ redaction primitives
def test_redaction_patterns_and_registered_secrets():
    register_secret("my-very-own-secret")
    out = redact_text(f"k={API_KEY} s={API_SECRET} t={BOT_TOKEN} x=my-very-own-secret ok=hello")
    assert "hello" in out and out.count(MASK) == 4
    assert_clean(out)


def test_scrub_masks_sensitive_keys_recursively():
    data = scrub({"rootpw": PASSWORD, "nested": {"api_secret": "x", "ok": 1, "msg": f"hi {API_SECRET}"},
                  "headers": {"X-Reseller-Secret": API_SECRET, "Authorization": "t"}, "list": [{"password": "p"}]})
    assert data["rootpw"] == MASK and data["nested"]["api_secret"] == MASK and data["nested"]["ok"] == 1
    assert data["headers"]["X-Reseller-Secret"] == MASK and data["list"][0]["password"] == MASK
    assert_clean(json.dumps(data))
    assert mask_value("th_res_ABCDEFGH") == f"{MASK}EFGH" and mask_value("abc") == MASK


def test_settings_repr_hides_secrets(tmp_path):
    s = make_settings(f"sqlite+aiosqlite:///{tmp_path}/x.db")
    for text in (repr(s), str(s), s.model_dump_json()):
        assert_clean(text)


def test_logging_filter_redacts_message_args_extra_and_exceptions(captured_logs):
    register_secret(API_SECRET)
    log = logging.getLogger("t")
    log.info("secret is %s", API_SECRET)
    log.info("event", extra={"fields": {"rootpw": PASSWORD, "endpoint": "/x", "detail": f"token {BOT_TOKEN}"}})
    log.info("extra attr", extra={"password": PASSWORD, "note": API_KEY})
    try:
        raise RuntimeError(f"failure using {API_SECRET} and {BOT_TOKEN}")
    except RuntimeError:
        log.exception("boom")
    out = captured_logs.getvalue()
    assert_clean(out)
    assert '"endpoint": "/x"' in out and "boom" in out and "Traceback" in out


# ------------------------------------------------------------------ end-to-end: nothing sensitive in logs / DB / callbacks
async def run_full_order_with_password(app):  # type: ignore[no-untyped-def]
    tg = app.tg
    await tg.click(Cat(a="c", pid=12, cy="m"))
    await tg.press("Skip (use default)")
    await tg.press("Skip")
    await tg.press("Skip")
    await tg.press("Root password")
    await tg.send(PASSWORD)
    await tg.press("Review")
    await tg.press("Confirm Order")


async def test_no_secrets_in_logs_during_real_flows(en, captured_logs):
    await run_full_order_with_password(en)
    en.fake.overrides["GET /services"] = (401, err("UNAUTHORIZED", f"bad {API_SECRET}"))
    await en.tg.click(Menu(a="srv"))
    en.fake.overrides.clear()
    await en.tg.click("pw:do:150:reboot")
    await en.tg.send("/health")
    out = captured_logs.getvalue()
    assert "trusthost_api_call" in out and "/orders/create" in out     # structured API logging is on …
    assert_clean(out)                                                   # … and clean
    entry = next(e for e in map(json.loads, out.splitlines())
                 if e.get("msg") == "trusthost_api_call" and e.get("endpoint") == "/orders/create")
    assert {"method", "endpoint", "status", "duration_ms", "telegram_user_id"} <= set(entry)
    assert entry["telegram_user_id"] == ADMIN_ID


async def test_root_password_is_never_persisted(en):
    await run_full_order_with_password(en)
    assert en.fake.last_body("POST", "/orders/create")["rootpw"] == PASSWORD   # it did reach TrustHost…
    db_bytes = pathlib.Path(en.repo.db_path).read_bytes()
    assert PASSWORD.encode() not in db_bytes                                  # …but never the database
    rows = await en.repo.list_audit()
    assert rows and PASSWORD not in repr(rows)
    assert all(PASSWORD not in (r.detail or "") for r in rows)


async def test_password_message_deleted_and_not_echoed(en):
    await en.tg.click(Cat(a="c", pid=12, cy="m"))
    for _ in range(3):
        await en.tg.press("Skip")
    await en.tg.press("Root password")
    await en.tg.send(PASSWORD)
    assert len(en.tg.deleted()) == 1
    assert PASSWORD not in en.tg.all_text()


async def test_invalid_password_message_is_also_deleted(en):
    await en.tg.click(Cat(a="c", pid=12, cy="m"))
    for _ in range(3):
        await en.tg.press("Skip")
    await en.tg.press("Root password")
    await en.tg.send("short")
    assert len(en.tg.deleted()) == 1 and "8–128" in en.tg.last_text()


async def test_password_field_of_custom_type_is_masked_and_deleted(en):
    en.fake.options = {"config_options": [], "custom_fields": [
        {"id": 3, "fieldname": "Panel password", "fieldtype": "password", "description": "", "fieldoptions": ""}]}
    await en.tg.click(Cat(a="c", pid=12, cy="m"))
    await en.tg.send("hunter2-hunter2")
    assert len(en.tg.deleted()) == 1
    await en.tg.press("Review")
    assert "hunter2" not in en.tg.all_text() and "••••••" in en.tg.last_text()


async def test_callback_data_is_compact_and_secret_free_everywhere(en):
    await run_full_order_with_password(en)
    for go in (lambda: en.tg.click(Menu(a="srv")), lambda: en.tg.click(Srv(a="d", id=150)), lambda: en.tg.click(Menu(a="support")),
               lambda: en.tg.click("tp:q:150:0"), lambda: en.tg.click(Menu(a="inv"))):
        await go()
    seen = 0
    for req in en.tg.sent():
        markup = req.reply_markup
        if isinstance(markup, InlineKeyboardMarkup):
            for row in markup.inline_keyboard:
                for b in row:
                    if b.callback_data:
                        seen += 1
                        assert len(b.callback_data.encode()) <= 64 and "th_" not in b.callback_data
                        assert PASSWORD not in b.callback_data and API_SECRET not in b.callback_data
    assert seen > 30


async def test_fsm_draft_wiped_after_order(en):
    from aiogram.fsm.storage.base import StorageKey
    await run_full_order_with_password(en)
    key = StorageKey(bot_id=en.bot.id, chat_id=ADMIN_ID, user_id=ADMIN_ID)
    assert PASSWORD not in str(await en.dp.storage.get_data(key))


async def test_audit_trail_records_actions_without_payloads(en):
    await en.tg.click("pd:0")  # noop garbage must not break anything
    await en.tg.click("i:pd:8841:a:0")
    await en.tg.click("pw:do:150:reboot")
    actions = [(r.action, r.resource, r.result) for r in await en.repo.list_audit(ADMIN_ID)]
    assert ("PAY_INVOICE", "invoice=8841", "success") in actions and ("POWER_REBOOT", "service=150", "success") in actions
    assert all(r.created_at for r in await en.repo.list_audit())


def test_client_never_keeps_secret_outside_http_headers(client):
    state = {k: v for k, v in vars(client).items() if k != "_http"}
    assert_clean(repr(state))


async def test_bot_ignores_group_chats_even_for_admins(en):
    from aiogram.types import Update
    raw = {"update_id": 900, "message": {"message_id": 1, "date": 1_700_000_000, "text": "/wallet",
           "entities": [{"type": "bot_command", "offset": 0, "length": 7}],
           "chat": {"id": -100123, "type": "supergroup", "title": "g"},
           "from": {"id": ADMIN_ID, "is_bot": False, "first_name": "A"}}}
    await en.dp.feed_raw_update(en.bot, raw)
    assert en.tg.sent() == [] and en.fake.calls == []        # no balance posted to the group, no API call
    cb = {"update_id": 901, "callback_query": {"id": "1", "chat_instance": "x", "data": "m:wal",
          "from": {"id": ADMIN_ID, "is_bot": False, "first_name": "A"}, "message": raw["message"]}}
    await en.dp.feed_raw_update(en.bot, cb)
    assert en.tg.sent() == [] and en.fake.calls == []


async def test_bot_commands_registered_per_language(en):
    from app.bot.setup import set_bot_commands
    from aiogram.methods import SetMyCommands
    await set_bot_commands(en.bot)
    calls = [r for r in en.session.requests if isinstance(r, SetMyCommands)]
    assert {c.language_code for c in calls} == {None, "fa"}
    by_lang = {c.language_code: c.commands for c in calls}
    assert [c.command for c in by_lang["fa"]] == [c.command for c in by_lang[None]]          # syntax stays English
    assert "سرورهای من" in by_lang["fa"][2].description and by_lang[None][2].description == "My servers"
