from __future__ import annotations

from aiogram.methods import SendMessage

from tests.conftest import ADMIN_ID


def sent_messages(app):  # type: ignore[no-untyped-def]
    return [r for r in app.session.requests if isinstance(r, SendMessage)]


async def setup_user(app, lang="en"):  # type: ignore[no-untyped-def]
    await app.repo.set_language(ADMIN_ID, lang)


async def test_first_poll_only_seeds_state_and_sends_nothing(app):
    await setup_user(app)
    await app.hub.notifier.run_once()
    assert sent_messages(app) == []
    assert await app.repo.get_states(ADMIN_ID, "tickets") == {"61": "Answered|2026-10-04 10:00:00"}
    assert await app.repo.get_states(ADMIN_ID, "services") == {"150": "Active", "151": "Suspended"}
    assert set(await app.repo.get_states(ADMIN_ID, "payments")) == {"8841", "8800"}
    assert await app.repo.get_last_poll(ADMIN_ID, "tickets") is not None


async def test_staff_reply_notifies_exactly_once(app):
    await setup_user(app)
    await app.hub.notifier.run_once()
    app.fake.ticket_replies[61].append({"id": 2, "admin": "Sara", "name": "Sara", "message": "Fixed <b>now</b>", "date": "2026-10-06 11:00:00"})
    app.fake.tickets[0].update(lastreply="2026-10-06 11:00:00", status="Answered")
    app.hub.client.invalidate("/tickets")
    await app.hub.notifier.run_once()
    msgs = sent_messages(app)
    assert len(msgs) == 1 and msgs[0].chat_id == ADMIN_ID
    assert "#482913" in msgs[0].text and "Fixed &lt;b&gt;now&lt;/b&gt;" in msgs[0].text      # escaped
    assert msgs[0].reply_markup.inline_keyboard[0][0].callback_data == "t:d:61:0"
    for _ in range(3):                                      # same state again → no duplicates, even after "restart"
        app.hub.client.invalidate("/tickets")
        await app.hub.notifier.run_once()
    assert len(sent_messages(app)) == 1


async def test_users_own_reply_does_not_notify_back(app):
    await setup_user(app)
    await app.hub.notifier.run_once()
    await app.hub.tickets.reply(ADMIN_ID, 61, "my reply")           # status becomes Customer-Reply, lastreply changes
    app.hub.client.invalidate("/tickets")
    await app.hub.notifier.run_once()
    assert sent_messages(app) == []


async def test_new_ticket_created_in_bot_is_not_reported(app):
    await setup_user(app)
    await app.hub.notifier.run_once()
    await app.hub.tickets.create(ADMIN_ID, dept_id=2, subject="s", message="m")
    app.hub.client.invalidate("/tickets")
    await app.hub.notifier.run_once()
    assert sent_messages(app) == []


async def test_service_status_change_notifies(app):
    await setup_user(app, "fa")
    await app.hub.notifier.run_once()
    app.fake.services[1]["status"] = "Active"
    app.hub.client.invalidate("/services")
    await app.hub.notifier.run_once()
    msgs = sent_messages(app)
    assert len(msgs) == 1 and "VPS Finland" in msgs[0].text and "Suspended" in msgs[0].text and "وضعیت تغییر کرد" in msgs[0].text


async def test_payment_confirmation_for_invoice_created_by_the_bot(app):
    await setup_user(app)
    r = await app.hub.orders.create(ADMIN_ID, __import__("tests.test_services", fromlist=["draft"]).draft())
    await app.hub.notifier.run_once()                         # first poll seeds (invoice already tracked as Unpaid)
    assert sent_messages(app) == []
    next(i for i in app.fake.invoices if i["id"] == r.invoice_id)["status"] = "Paid"   # paid online elsewhere
    app.hub.client.invalidate("/invoices")
    await app.hub.notifier.run_once()
    msgs = sent_messages(app)
    assert len(msgs) == 1 and f"#{r.invoice_id}" in msgs[0].text and "was paid" in msgs[0].text


async def test_preferences_disable_notifications_and_reenable_reseeds(app):
    await setup_user(app)
    await app.hub.notifier.run_once()
    await app.repo.set_notification_pref(ADMIN_ID, "tickets", False)
    app.fake.ticket_replies[61].append({"id": 2, "admin": "Sara", "name": "Sara", "message": "x", "date": "2026-10-06 11:00:00"})
    app.fake.tickets[0]["lastreply"] = "2026-10-06 11:00:00"
    app.hub.client.invalidate("/tickets")
    await app.hub.notifier.run_once()
    assert sent_messages(app) == []
    await app.tg.click("st:nt:tickets")                        # re-enable through the UI → state is re-seeded
    app.hub.client.invalidate("/tickets")
    await app.hub.notifier.run_once()
    assert sent_messages(app) == []                            # old reply is not replayed


async def test_api_failure_during_poll_is_swallowed_and_state_kept(app):
    await setup_user(app)
    await app.hub.notifier.run_once()
    before = await app.repo.get_states(ADMIN_ID, "tickets")
    app.fake.overrides["GET /tickets"] = (500, {"success": False, "error": "SERVER_ERROR"})
    app.hub.client.invalidate("/tickets")
    await app.hub.notifier.run_once()                           # must not raise
    assert await app.repo.get_states(ADMIN_ID, "tickets") == before


async def test_poll_request_volume_is_small(app):
    await setup_user(app)
    await app.hub.notifier.run_once()
    assert len(app.fake.calls) == 3                             # tickets + services + invoices, nothing else
