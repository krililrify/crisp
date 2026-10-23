"""单实例持久化任务执行器。失败重试；任务租约在进程崩溃后自动恢复。"""

import time, logging, html
from pathlib import Path
import httpx
from sqlalchemy import select, or_, and_, delete
from .db import Session
from .models import *
from .services import *
from .security import decrypt, validate_url
from .integrations import (
    tg,
    telegram_config,
    ExternalError,
    entities_markdown,
    telegram_chunks,
    telegram_html,
)
from .uploads import save_image
from .config import settings

log = logging.getLogger(__name__)


def ensure_topic(customer_id):
    # Commit mapping before sending any message; never blindly recreate a lost/deleted topic.
    with Session() as db:
        c = db.get(Customer, customer_id)
        site = db.get(Site, c.site_id)
        cfg = telegram_config(db)
        topic = db.get(TelegramTopic, c.id)
        if topic and topic.thread_id:
            return topic.chat_id, topic.thread_id
        if topic and topic.error:
            raise ExternalError("话题创建结果不明确，请管理员修复映射：" + topic.error)
        if not topic:
            topic = TelegramTopic(
                customer_id=c.id,
                chat_id=cfg["chat_id"],
                error="创建中；若执行器中断请人工核对",
            )
            db.add(topic)
            db.commit()
        try:
            result = tg(
                db,
                "createForumTopic",
                {"chat_id": cfg["chat_id"], "name": f"[{site.name}] {c.email}"[:128]},
            )
        except Exception:
            topic.error = "创建失败或结果未知，请检查 Telegram 后修复映射"
            db.commit()
            raise
        topic.thread_id = result["message_thread_id"]
        topic.error = ""
        db.commit()
        return topic.chat_id, topic.thread_id


def send_telegram(task):
    with Session() as db:
        m = db.get(Message, task.payload["message_id"])
        conv = db.get(Conversation, m.conversation_id)
        c = db.get(Customer, conv.customer_id)
        site = db.get(Site, c.site_id)
        chat, thread = ensure_topic(c.id)
        topic = db.get(TelegramTopic, c.id)
        cfg = telegram_config(db)
        if cfg["chat_id"] != chat:
            raise ExternalError("群组已变更，需修复话题映射")
        try:
            # Reopen is harmless even after a manual close. Telegram reports already-open as an error.
            try:
                tg(
                    db,
                    "reopenForumTopic",
                    {"chat_id": chat, "message_thread_id": thread},
                )
            except ExternalError as exc:
                if "TOPIC_NOT_MODIFIED" not in str(exc):
                    raise
            topic.closed = False
            prefix = (
                f"[{site.name}] {c.email}\n"
                + ("客户消息" if m.source == "visitor" else "客服 / 自动回复")
                + "\n"
            )
            formatted = telegram_html(m.body)
            rich = len(formatted.encode("utf-16-le")) < 6000
            chunks = [formatted] if rich else telegram_chunks(m.body)
            for index, chunk in enumerate(chunks):
                key = f"part:{task.id}:{index}"
                if db.get(SystemSetting, key):
                    continue
                payload = {
                    "chat_id": chat,
                    "message_thread_id": thread,
                    "text": (
                        (html.escape(prefix) if rich else prefix) if index == 0 else ""
                    )
                    + chunk,
                }
                if rich:
                    payload["parse_mode"] = "HTML"
                tg(db, "sendMessage", payload)
                put_setting(db, key, {"sent": True})
                db.commit()
            if m.attachment_id:
                key = f"photo:{task.id}"
                if not db.get(SystemSetting, key):
                    a = db.get(Attachment, m.attachment_id)
                    with open(a.path, "rb") as photo:
                        tg(
                            db,
                            "sendPhoto",
                            {"chat_id": chat, "message_thread_id": thread},
                            files={"photo": ("image.jpg", photo, "image/jpeg")},
                        )
                    put_setting(db, key, {"sent": True})
                    db.commit()
            topic.error = ""
            m.status = "forwarded"
            db.commit()
        except Exception as exc:
            topic.error = str(exc)[:500]
            db.commit()
            raise


def send_bark(task):
    with Session() as db:
        d = db.get(BarkDevice, task.payload["device_id"])
        if not d or not d.enabled:
            return 204
        test = task.payload.get("test")
        if not test and not setting(db, "bark", {"enabled": True}).get("enabled", True):
            return 204
        title = "客服系统测试"
        body = "Bark API 接受请求不等于设备已收到通知。"
        target = settings().public_url + "/admin/"
        if not test:
            m = db.get(Message, task.payload["message_id"])
            conv = db.get(Conversation, m.conversation_id)
            c = db.get(Customer, conv.customer_id)
            site = db.get(Site, c.site_id)
            title = f"[{site.name}] 新客户消息"
            body = c.email + "：" + (m.body[:200] or "[图片]")
            target += f"?conversation={conv.id}"
        url = validate_url(decrypt(d.url_encrypted))
        try:
            r = httpx.post(
                url,
                json={"title": title, "body": body, "url": target, "group": "客服"},
                timeout=15,
                follow_redirects=False,
            )
            if r.status_code != 200 or r.json().get("code") != 200:
                raise ExternalError("Bark API 未接受请求", r.status_code)
            return r.status_code
        except (httpx.HTTPError, ValueError):
            raise ExternalError("Bark 网络异常或响应无效")


def handle_update(task):
    update = task.payload
    with Session() as db:
        if db.get(TelegramUpdate, update["update_id"]):
            return
        cfg = telegram_config(db)
        msg = update.get("message") or {}
        sender = msg.get("from") or {}
        if (
            str((msg.get("chat") or {}).get("id")) != cfg["chat_id"]
            or sender.get("is_bot")
            or sender.get("id") not in cfg["admin_ids"]
            or msg.get("sender_chat")
        ):
            db.add(TelegramUpdate(update_id=update["update_id"]))
            db.commit()
            return
        topic = db.scalar(
            select(TelegramTopic).where(
                TelegramTopic.chat_id == cfg["chat_id"],
                TelegramTopic.thread_id == msg.get("message_thread_id", -1),
            )
        )
        if not topic:
            raise ExternalError("收到未映射话题消息，请检查映射")
        c = db.get(Customer, topic.customer_id)
        conv = db.scalar(
            select(Conversation)
            .where(Conversation.customer_id == c.id)
            .with_for_update()
        )
        s = current_session(db, c.id)
        text = msg.get("text", msg.get("caption", ""))[:12000]
        command = text.split()[0].split("@")[0] if text.startswith("/") else ""
        if command in ("/close", "/reopen"):
            conv.status = "resolved" if command == "/close" else "pending"
            enqueue(
                db,
                "topic_state",
                {"customer_id": c.id, "closed": command == "/close"},
                f"state:{update['update_id']}",
            )
        elif command == "/quick":
            query = text.partition(" ")[2].strip()
            quick = list(db.scalars(select(QuickReply).order_by(QuickReply.title)))
            matches = [
                q
                for q in quick
                if query and (query.casefold() in q.title.casefold() or q.id == query)
            ]
            if len(matches) == 1:
                store_message(db, c, conv, s, "telegram", matches[0].body)
            else:
                content = "快捷回复：\n" + "\n".join(
                    f"/quick {q.id} — {q.title}" for q in quick
                )
                enqueue(
                    db,
                    "telegram_text",
                    {
                        "chat_id": cfg["chat_id"],
                        "thread_id": topic.thread_id,
                        "text": content[:3500] or "暂无快捷回复",
                    },
                    f"quick:{update['update_id']}",
                )
        elif text or msg.get("photo"):
            attachment = None
            if msg.get("photo"):
                file = tg(db, "getFile", {"file_id": msg["photo"][-1]["file_id"]})
                if file.get("file_size", 0) > settings().max_upload_bytes:
                    raise ExternalError("Telegram 图片超过上传限制")
                # Bound streaming download rather than trusting Content-Length.
                data = bytearray()
                with httpx.stream(
                    "GET",
                    f"https://api.telegram.org/file/bot{cfg['bot_token']}/{file['file_path']}",
                    timeout=20,
                ) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > settings().max_upload_bytes:
                            raise ExternalError("Telegram 图片超过上传限制")
                attachment = save_image(db, bytes(data), c.id, s.id if s else None).id
            body = entities_markdown(
                text, msg.get("entities", msg.get("caption_entities", []))
            )
            store_message(db, c, conv, s, "telegram", body, attachment, telegram=False)
            conv.status = "active"
        db.add(TelegramUpdate(update_id=update["update_id"]))
        db.commit()


def execute(task):
    if task.kind == "telegram":
        return send_telegram(task)
    if task.kind == "bark":
        return send_bark(task)
    if task.kind == "telegram_update":
        return handle_update(task)
    with Session() as db:
        p = task.payload
        if task.kind == "topic_state":
            t = db.get(TelegramTopic, p["customer_id"])
            if not t or not t.thread_id:
                return
            try:
                tg(
                    db,
                    "closeForumTopic" if p["closed"] else "reopenForumTopic",
                    {"chat_id": t.chat_id, "message_thread_id": t.thread_id},
                )
            except ExternalError as e:
                if "TOPIC_NOT_MODIFIED" not in str(e):
                    raise
            t.closed = p["closed"]
            db.commit()
        elif task.kind == "telegram_text":
            tg(
                db,
                "sendMessage",
                {
                    "chat_id": p["chat_id"],
                    "message_thread_id": p["thread_id"],
                    "text": p["text"],
                },
            )


def run_once():
    with Session() as db:
        task = db.scalar(
            select(Delivery)
            .where(
                or_(
                    and_(Delivery.status == "pending", Delivery.next_attempt <= now()),
                    and_(Delivery.status == "working", Delivery.next_attempt <= now()),
                )
            )
            .order_by(Delivery.next_attempt, Delivery.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not task:
            return False
        task.status = "working"
        task.attempts += 1
        task.next_attempt = now() + 600
        db.commit()
        ident = task.id
    try:
        status = execute(task)
        with Session() as db:
            t = db.get(Delivery, ident)
            t.status = "sent"
            t.sent_at = now()
            t.http_status = status
            t.error = ""
            db.commit()
    except Exception as e:
        # Never log raw request URLs, tokens, webhook bodies or device keys.
        error = (
            str(e)[:500]
            if isinstance(e, ExternalError)
            else "任务执行失败：" + type(e).__name__
        )
        with Session() as db:
            t = db.get(Delivery, ident)
            t.error = error
            t.http_status = getattr(e, "status", None)
            t.status = "failed" if t.attempts >= 8 else "pending"
            t.next_attempt = now() + max(
                min(3600, 2**t.attempts * 5), getattr(e, "retry_after", 0) or 0
            )
            db.commit()
        log.warning("delivery %s: %s", ident, error)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    last_cleanup = 0
    while True:
        try:
            if now() - last_cleanup > 3600:
                with Session() as db:
                    db.execute(
                        delete(LoginAttempt).where(
                            LoginAttempt.created_at < now() - 86400
                        )
                    )
                    db.execute(
                        delete(AdminSession).where(
                            AdminSession.expires_at < now() - 86400
                        )
                    )
                    db.commit()
                last_cleanup = now()
            Path("/tmp/support-worker-heartbeat").touch()
            if not run_once():
                time.sleep(1)
        except Exception:
            log.error("任务队列数据库暂不可用")
            time.sleep(5)
