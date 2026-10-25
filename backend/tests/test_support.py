import io, uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import pytest
from PIL import Image
from sqlalchemy import select, func
from fastapi.websockets import WebSocketDisconnect
from app.db import Session, engine
from app.models import *
from app.security import digest, render, encrypt, decrypt
from app.services import put_setting, setting, store_message
from app.worker import run_once, ensure_topic
from app.integrations import ExternalError, entities_markdown
from conftest import start, visitor_headers


def send(client, site, s, text="hello", ident=None, attachment=None):
    return client.post(
        f"/api/sites/{site['id']}/messages",
        json={
            "body": text,
            "client_id": ident or str(uuid.uuid4()),
            "attachment_id": attachment,
        },
        headers=visitor_headers(s),
    )


def history(client, site, s):
    return client.get(f"/api/sites/{site['id']}/messages", headers=visitor_headers(s))


def telegram_setup(db):
    put_setting(
        db,
        "telegram",
        {
            "token": encrypt("123456:TEST"),
            "secret": encrypt("test-secret"),
            "chat_id": "-1001234",
            "admin_ids": [42],
        },
    )
    db.commit()


def test_email_reuses_customer_but_never_history(admin, site):
    a = start(admin, site, "Alice@example.com")
    assert send(admin, site, a, "private").status_code == 200
    b = start(admin, site, "alice@example.com")
    assert (
        a["conversation_id"] == b["conversation_id"]
        and a["session_id"] != b["session_id"]
    )
    assert history(admin, site, b).json() == []
    assert history(admin, site, a).json()[0]["body"] == "private"
    assert (
        admin.get(
            "/api/admin/conversations/" + a["conversation_id"] + "/messages"
        ).json()[0]["body"]
        == "private"
    )


def test_expiry_is_fixed_and_denies_history(admin, site):
    s = start(admin, site)
    send(admin, site, s)
    with Session() as db:
        visitor = db.get(VisitorSession, s["session_id"])
        visitor.expires_at = now() - 1
        db.commit()
    assert history(admin, site, s).status_code == 401
    assert send(admin, site, s).status_code == 401
    fresh = start(admin, site)
    assert history(admin, site, fresh).json() == []


def test_site_and_token_isolation(admin, site):
    a = start(admin, site)
    send(admin, site, a)
    b = admin.post("/api/admin/sites", json={"name": "第二站"}).json()
    assert history(admin, b, a).status_code == 403
    assert history(admin, site, {"token": "made-up"}).status_code == 401
    new = start(admin, b)
    assert a["conversation_id"] != new["conversation_id"]
    assert (
        admin.get(
            "/api/sites/" + site["id"] + "/messages?email=a@example.com"
        ).status_code
        == 401
    )


def test_message_dedupe_and_outbox_atomic(admin, site):
    s = start(admin, site)
    ident = str(uuid.uuid4())
    one = send(admin, site, s, "message", ident)
    two = send(admin, site, s, "message", ident)
    assert one.json()["id"] == two.json()["id"]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 1
        assert db.scalar(select(func.count()).select_from(Delivery)) == 1
        assert db.scalar(select(Conversation)).unread == 1


def test_admin_csrf_expiry_password(admin, site):
    assert (
        admin.post(
            "/api/admin/sites", json={"name": "bad"}, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    assert (
        admin.post(
            "/api/admin/sites",
            json={"name": "bad"},
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    r = admin.post(
        "/api/admin/password",
        json={
            "old_password": "test-admin-password",
            "new_password": "new-admin-password",
        },
    )
    assert r.status_code == 200 and admin.get("/api/admin/me").status_code == 401


def test_login_rate_limit(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/admin/login",
                json={"username": "admin", "password": "wrong"},
                headers={"Origin": "http://testserver"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "wrong"},
            headers={"Origin": "http://testserver"},
        ).status_code
        == 429
    )


def test_markdown_is_safe():
    result = render(
        "# 标题\n**粗体** *斜体*\n\n- 列表\n\n`code`\n\n```py\npass\n```\n![图](https://example.com/a.png)\n[x](javascript:alert(1))\n<script>alert(1)</script>"
    )
    assert (
        "<h1>" in result
        and "<strong>" in result
        and "<em>" in result
        and "<ul>" in result
        and "<pre>" in result
        and "<img" in result
    )
    assert "<script" not in result and 'href="javascript:' not in result
    assert 'src="http://' not in render("![x](http://example.com/image)")


def test_upload_validation_and_acl(admin, site):
    s = start(admin, site)
    bad = admin.post(
        f"/api/sites/{site['id']}/uploads",
        files={"file": ("fake.png", b"<script>", "image/png")},
        headers=visitor_headers(s),
    )
    assert bad.status_code == 422
    out = io.BytesIO()
    Image.new("RGB", (5, 5)).save(out, "PNG")
    r = admin.post(
        f"/api/sites/{site['id']}/uploads",
        files={"file": ("real.png", out.getvalue(), "image/png")},
        headers=visitor_headers(s),
    )
    a = r.json()["id"]
    assert send(admin, site, s, "picture", attachment=a).status_code == 200
    other = start(admin, site)
    # Clear admin cookie so it cannot grant attachment access in this visitor test.
    admin.cookies.clear()
    url = f"/api/attachments/{a}?site_id={site['id']}"
    assert admin.get(url, headers=visitor_headers(s)).status_code == 200
    assert admin.get(url, headers=visitor_headers(other)).status_code == 403
    assert send(admin, site, other, "stolen", attachment=a).status_code == 403


def test_auto_rules_once_cooldown_and_no_loop(admin, site):
    for kind, keyword in [("welcome", ""), ("keyword", "help")]:
        assert (
            admin.post(
                "/api/admin/rules",
                json={
                    "site_id": site["id"],
                    "kind": kind,
                    "keyword": keyword,
                    "body": "auto " + kind,
                },
            ).status_code
            == 200
        )
    s = start(admin, site)
    send(admin, site, s, "help")
    send(admin, site, s, "help again")
    rows = history(admin, site, s).json()
    assert len([m for m in rows if m["source"] == "auto"]) == 2
    assert len(rows) == 4


def test_bark_secrets_batch_and_host_validation(admin):
    assert (
        admin.post(
            "/api/admin/bark/devices",
            json={"name": "bad", "url": "https://127.0.0.1/key"},
        ).status_code
        == 422
    )
    r = admin.post(
        "/api/admin/bark/batch",
        json={
            "urls": "https://api.day.app/secret-one,\nhttps://api.day.app/secret-two\nhttps://api.day.app/secret-one"
        },
    )
    assert r.json()["added"] == 2
    assert "secret-one" not in admin.get("/api/admin/bark").text
    with Session() as db:
        d = db.scalar(select(BarkDevice))
        assert "secret" not in d.url_encrypted
        assert decrypt(d.url_encrypted).startswith("https://api.day.app/")


def test_worker_persistent_retry_does_not_lose_message(admin, site, monkeypatch):
    s = start(admin, site)
    send(admin, site, s)
    monkeypatch.setattr(
        "app.worker.execute", Mock(side_effect=ExternalError("offline", 503))
    )
    assert run_once()
    with Session() as db:
        t = db.scalar(select(Delivery))
        assert t.status == "pending" and t.attempts == 1 and t.http_status == 503
        assert db.scalar(select(func.count()).select_from(Message)) == 1
        t.next_attempt = now() - 1
        db.commit()
    monkeypatch.setattr("app.worker.execute", Mock(return_value=200))
    assert run_once()
    with Session() as db:
        assert db.scalar(select(Delivery)).status == "sent"


def test_bark_failure_isolated_per_device(admin, site, monkeypatch):
    for i in range(2):
        admin.post(
            "/api/admin/bark/devices",
            json={"name": str(i), "url": f"https://api.day.app/key{i}"},
        )
    s = start(admin, site)
    send(admin, site, s)

    def execute(t):
        if t.kind == "telegram" or t.payload["device_id"] == first:
            raise ExternalError("failed")
        return 200

    with Session() as db:
        first = db.scalar(select(BarkDevice)).id
    monkeypatch.setattr("app.worker.execute", execute)
    for _ in range(3):
        assert run_once()
    with Session() as db:
        statuses = [
            t.status
            for t in db.scalars(select(Delivery).where(Delivery.kind == "bark"))
        ]
        assert sorted(statuses) == ["pending", "sent"]


def test_topic_created_once_and_ambiguous_failure_stops_creation(
    admin, site, monkeypatch
):
    s = start(admin, site)
    with Session() as db:
        telegram_setup(db)
        c = db.get(VisitorSession, s["session_id"]).customer_id
    mock = Mock(return_value={"message_thread_id": 99})
    monkeypatch.setattr("app.worker.tg", mock)
    assert ensure_topic(c) == ("-1001234", 99)
    assert ensure_topic(c) == ("-1001234", 99)
    assert mock.call_count == 1
    s2 = start(admin, site, "other@example.com")
    with Session() as db:
        c2 = db.get(VisitorSession, s2["session_id"]).customer_id
    mock.side_effect = ExternalError("timeout")
    with pytest.raises(ExternalError):
        ensure_topic(c2)
    with pytest.raises(ExternalError):
        ensure_topic(c2)
    assert mock.call_count == 2


def test_webhook_auth_dedupe_authorization_and_no_loop(admin, site, monkeypatch):
    s = start(admin, site)
    with Session() as db:
        telegram_setup(db)
        cid = db.get(VisitorSession, s["session_id"]).customer_id
        db.add(TelegramTopic(customer_id=cid, chat_id="-1001234", thread_id=99))
        db.commit()
    headers = {"X-Telegram-Bot-Api-Secret-Token": "test-secret"}

    def payload(uid, user=42, bot=False, chat=-1001234):
        return {
            "update_id": uid,
            "message": {
                "message_id": uid,
                "chat": {"id": chat},
                "message_thread_id": 99,
                "from": {"id": user, "is_bot": bot},
                "text": "**客服**",
            },
        }

    assert admin.post("/api/telegram/webhook", json=payload(1)).status_code == 403
    for p in [
        payload(1),
        payload(1),
        payload(2, user=43),
        payload(3, bot=True),
        payload(4, chat=-1005555),
    ]:
        assert (
            admin.post("/api/telegram/webhook", json=p, headers=headers).status_code
            == 200
        )
    for _ in range(4):
        assert run_once()
    rows = history(admin, site, s).json()
    assert len(rows) == 1 and rows[0]["source"] == "telegram"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(TelegramUpdate)) == 4
        assert (
            db.scalar(
                select(func.count())
                .select_from(Delivery)
                .where(Delivery.kind == "telegram")
            )
            == 0
        )


def test_websocket_requires_token_and_site(admin, site):
    s = start(admin, site)
    with admin.websocket_connect(
        "/api/ws", headers={"Origin": "http://testserver"}
    ) as ws:
        ws.send_json({"role": "visitor", "site_id": site["id"], "token": s["token"]})
        assert ws.receive_json()["type"] == "changed"
    with pytest.raises(WebSocketDisconnect):
        with admin.websocket_connect(
            "/api/ws", headers={"Origin": "http://testserver"}
        ) as ws:
            ws.send_json({"role": "visitor", "site_id": site["id"], "token": "wrong"})
            ws.receive_json()


def test_admin_reply_only_enters_current_session(admin, site):
    a = start(admin, site)
    b = start(admin, site)
    r = admin.post(
        f"/api/admin/conversations/{a['conversation_id']}/messages",
        json={"body": "latest only", "client_id": str(uuid.uuid4())},
    )
    assert r.status_code == 200
    assert history(admin, site, a).json() == []
    assert history(admin, site, b).json()[0]["body"] == "latest only"


def test_telegram_utf16_conversion():
    result = entities_markdown("😀 hello", [{"type": "bold", "offset": 3, "length": 5}])
    assert result == "😀 **hello**"


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL concurrency requires TEST_DATABASE_URL",
)
def test_concurrent_email_and_messages(admin, site):
    from fastapi.testclient import TestClient
    from app.main import app

    def begin(_):
        with TestClient(app) as c:
            return start(c, site, "race@example.com")

    with ThreadPoolExecutor(max_workers=6) as pool:
        sessions = list(pool.map(begin, range(6)))
    assert len(set(s["conversation_id"] for s in sessions)) == 1
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Customer)) == 1


def test_telegram_forwarding_format_image_and_progress(admin, site, monkeypatch):
    s = start(admin, site)
    with Session() as db:
        telegram_setup(db)
    calls = []

    def fake(db, method, payload=None, files=None):
        calls.append((method, payload))
        if method == "createForumTopic":
            return {"message_thread_id": 999}
        if method == "reopenForumTopic":
            raise ExternalError("TOPIC_NOT_MODIFIED")
        return {"message_id": 123}

    monkeypatch.setattr("app.worker.tg", fake)
    send(admin, site, s, "# Hello\n**bold** [link](https://example.com)")
    assert run_once()
    methods = [c[0] for c in calls]
    assert methods == ["createForumTopic", "reopenForumTopic", "sendMessage"]
    sent = calls[-1][1]
    assert sent["parse_mode"] == "HTML" and "<b>bold</b>" in sent["text"]
    assert history(admin, site, s).json()[0]["status"] == "forwarded"


def test_topic_missing_is_reported_and_repair_retains_history(admin, site, monkeypatch):
    s = start(admin, site)
    send(admin, site, s, "do not lose")
    with Session() as db:
        telegram_setup(db)
        cid = db.get(VisitorSession, s["session_id"]).customer_id
        db.add(TelegramTopic(customer_id=cid, chat_id="-1001234", thread_id=55))
        db.commit()
    monkeypatch.setattr(
        "app.worker.tg", Mock(side_effect=ExternalError("TOPIC_DELETED", 400))
    )
    assert run_once()
    assert "TOPIC_DELETED" in admin.get("/api/admin/topics").text
    assert (
        admin.put(
            "/api/admin/topics/" + cid, json={"chat_id": "-1001234", "thread_id": 66}
        ).status_code
        == 200
    )
    logs = admin.get("/api/admin/deliveries").json()
    assert logs[0]["error"]
    assert (
        admin.post("/api/admin/deliveries/" + logs[0]["id"] + "/retry").status_code
        == 200
    )
    assert history(admin, site, s).json()[0]["body"] == "do not lose"


def test_telegram_close_reopen_quick(admin, site):
    s = start(admin, site)
    admin.post(
        "/api/admin/quick-replies", json={"title": "windows", "body": "**更新**订阅"}
    )
    with Session() as db:
        telegram_setup(db)
        cid = db.get(VisitorSession, s["session_id"]).customer_id
        db.add(TelegramTopic(customer_id=cid, chat_id="-1001234", thread_id=55))
        db.commit()

    def post_update(uid, text):
        payload = {
            "update_id": uid,
            "message": {
                "chat": {"id": -1001234},
                "message_thread_id": 55,
                "from": {"id": 42},
                "text": text,
            },
        }
        assert (
            admin.post(
                "/api/telegram/webhook",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            ).status_code
            == 200
        )
        assert run_once()

    post_update(10, "/quick windows")
    assert history(admin, site, s).json()[0]["body"] == "**更新**订阅"
    # Clear outgoing jobs so command input is next.
    with Session() as db:
        for task in db.scalars(select(Delivery).where(Delivery.status == "pending")):
            task.status = "sent"
        db.commit()
    post_update(11, "/close")
    assert (
        admin.get("/api/admin/conversations/" + s["conversation_id"]).json()["status"]
        == "resolved"
    )
    send(admin, site, s, "new inquiry")
    assert (
        admin.get("/api/admin/conversations/" + s["conversation_id"]).json()["status"]
        == "pending"
    )


def test_websocket_expires_during_connection(admin, site):
    s = start(admin, site)
    with pytest.raises(WebSocketDisconnect):
        with admin.websocket_connect(
            "/api/ws", headers={"Origin": "http://testserver"}
        ) as ws:
            ws.send_json(
                {"role": "visitor", "site_id": site["id"], "token": s["token"]}
            )
            ws.receive_json()
            with Session() as db:
                db.get(VisitorSession, s["session_id"]).expires_at = now() - 1
                db.commit()
            ws.receive_json()


def test_disabled_site_denies_existing_credentials(admin, site):
    s = start(admin, site)
    admin.put(
        "/api/admin/sites/" + site["id"], json={"name": "disabled", "enabled": False}
    )
    assert history(admin, site, s).status_code == 403
    assert send(admin, site, s).status_code == 403


def test_rule_timezone_validation(admin, site):
    assert (
        admin.post(
            "/api/admin/rules",
            json={
                "site_id": site["id"],
                "kind": "offline",
                "body": "hi",
                "timezone": "not-a-zone",
            },
        ).status_code
        == 422
    )


def test_real_bark_result_records_http_status(admin, monkeypatch):
    admin.post(
        "/api/admin/bark/devices",
        json={"name": "phone", "url": "https://api.day.app/testkey"},
    )
    admin.post("/api/admin/bark/test")
    mock = Mock(status_code=200)
    mock.json.return_value = {"code": 200}
    monkeypatch.setattr("app.worker.httpx.post", Mock(return_value=mock))
    assert run_once()
    row = admin.get("/api/admin/deliveries").json()[0]
    assert (
        row["http_status"] == 200 and row["device_name"] == "phone" and row["sent_at"]
    )


def test_login_cookie_flags(client):
    r = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "test-admin-password"},
        headers={"Origin": "http://testserver"},
    )
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_admin_send_idempotent_even_without_visitor_session(admin, site):
    s = start(admin, site)
    with Session() as db:
        db.get(VisitorSession, s["session_id"]).expires_at = now() - 1
        db.commit()
    path = f"/api/admin/conversations/{s['conversation_id']}/messages"
    data = {"body": "offline reply", "client_id": str(uuid.uuid4())}
    a = admin.post(path, json=data)
    b = admin.post(path, json=data)
    assert a.status_code == b.status_code == 200
    assert a.json()["id"] == b.json()["id"]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 1


def test_overnight_work_hours_use_previous_workday(admin, site, monkeypatch):
    from datetime import datetime as real_datetime

    class Clock:
        @staticmethod
        def now(tz):
            return real_datetime(
                2026, 10, 24, 1, 0, tzinfo=tz
            )  # Saturday, Friday overnight shift

    monkeypatch.setattr("app.services.datetime", Clock)
    admin.post(
        "/api/admin/rules",
        json={
            "site_id": site["id"],
            "kind": "offline",
            "body": "offline",
            "start_hour": 22,
            "end_hour": 6,
            "weekdays": [4],
        },
    )
    s = start(admin, site)
    send(admin, site, s, "hello")
    assert len(history(admin, site, s).json()) == 1


def test_migration_matches_model_schema(tmp_path, monkeypatch):
    from alembic.config import Config
    from alembic import command
    from alembic.migration import MigrationContext
    from alembic.autogenerate import compare_metadata
    from sqlalchemy import create_engine
    from app.db import Base

    # Exercise the frozen migration on an independent database, not create_all.
    migrated = create_engine("sqlite:///" + str(tmp_path / "migrations.db"))
    monkeypatch.setattr("app.db.engine", migrated)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    with migrated.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_upload_max_size_and_message_rate_limit(admin, site):
    s = start(admin, site)
    r = admin.post(
        f"/api/sites/{site['id']}/uploads",
        files={"file": ("big.jpg", b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")},
        headers=visitor_headers(s),
    )
    assert r.status_code == 413
    for _ in range(30):
        assert send(admin, site, s).status_code == 200
    assert send(admin, site, s).status_code == 429


def test_topic_unique_repair_and_site_search(admin, site):
    s = start(admin, site)
    s2 = start(admin, site, "b@example.com")
    send(admin, site, s, "search target")
    with Session() as db:
        ca = db.get(VisitorSession, s["session_id"]).customer_id
        cb = db.get(VisitorSession, s2["session_id"]).customer_id
    assert (
        admin.put(
            "/api/admin/topics/" + ca, json={"chat_id": "-1001234", "thread_id": 5}
        ).status_code
        == 200
    )
    assert (
        admin.put(
            "/api/admin/topics/" + cb, json={"chat_id": "-1001234", "thread_id": 5}
        ).status_code
        == 409
    )
    found = admin.get(
        "/api/admin/conversations", params={"site_id": site["id"], "q": "search target"}
    ).json()
    assert len(found) == 1 and found[0]["email"] == "a@example.com"


def test_idle_websocket_disconnect_releases_server_task(admin, site):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.main import realtime

    s = start(admin, site)
    socket = SimpleNamespace(
        accept=AsyncMock(),
        receive_json=AsyncMock(
            return_value={"role": "visitor", "site_id": site["id"], "token": s["token"]}
        ),
        receive=AsyncMock(return_value={"type": "websocket.disconnect", "code": 1000}),
        send_json=AsyncMock(),
        close=AsyncMock(),
        headers={"origin": "http://testserver"},
        cookies={},
    )
    asyncio.run(asyncio.wait_for(realtime(socket), timeout=0.5))
    socket.receive.assert_awaited_once()


def test_websocket_rejects_malformed_auth(client):
    for payload in ([], {"role": "unknown"}, {"role": "visitor", "token": ["bad"]}):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/ws", headers={"Origin": "http://testserver"}
            ) as ws:
                ws.send_json(payload)
                ws.receive_json()
