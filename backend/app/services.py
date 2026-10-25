from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from fastapi import HTTPException
from .models import *
from .security import render


def setting(db, key, default=None):
    s = db.get(SystemSetting, key)
    return s.value if s else (default or {})


def put_setting(db, key, value):
    s = db.get(SystemSetting, key)
    if s:
        s.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


def enqueue(db, kind, payload, key):
    if not db.scalar(select(Delivery).where(Delivery.dedupe_key == key)):
        db.add(Delivery(kind=kind, payload=payload, dedupe_key=key))


def message_dict(m):
    return {
        "id": m.id,
        "body": m.body,
        "html": render(m.body),
        "attachment_id": m.attachment_id,
        "source": m.source,
        "created_at": m.created_at,
        "status": m.status,
        "client_id": m.client_id,
    }


def current_session(db, customer_id):
    return db.scalar(
        select(VisitorSession)
        .where(
            VisitorSession.customer_id == customer_id, VisitorSession.expires_at > now()
        )
        .order_by(VisitorSession.created_at.desc())
        .limit(1)
    )


def store_message(
    db, c, conv, s, source, body, attachment_id=None, client_id=None, telegram=True
):
    if not body.strip() and not attachment_id:
        raise HTTPException(422, "消息不能为空")
    request_key = (
        (
            source
            + ":"
            + (s.id if source == "visitor" and s else conv.id)
            + ":"
            + client_id
        )
        if client_id
        else None
    )
    if request_key:
        old = db.scalar(select(Message).where(Message.request_key == request_key))
        if old:
            return old
    if attachment_id:
        a = db.get(Attachment, attachment_id)
        if (
            not a
            or a.customer_id != c.id
            or (source == "visitor" and a.visitor_session_id != s.id)
        ):
            raise HTTPException(403, "不能发送此附件")
    m = Message(
        conversation_id=conv.id,
        visitor_session_id=s.id if s else None,
        source=source,
        body=body,
        attachment_id=attachment_id,
        client_id=client_id,
        request_key=request_key,
    )
    db.add(m)
    db.flush()
    conv.updated_at = now()
    c.last_seen = now()
    if source == "visitor":
        conv.unread += 1
        if conv.status == "resolved":
            conv.status = "pending"
    if telegram:
        enqueue(db, "telegram", {"message_id": m.id}, "telegram:" + m.id)
    if source == "visitor" and setting(db, "bark", {"enabled": True}).get(
        "enabled", True
    ):
        for d in db.scalars(select(BarkDevice).where(BarkDevice.enabled.is_(True))):
            enqueue(
                db,
                "bark",
                {"message_id": m.id, "device_id": d.id},
                "bark:" + m.id + ":" + d.id,
            )
    return m


def apply_rules(db, site, c, conv, s, body):
    count = db.scalar(
        select(__import__("sqlalchemy").func.count())
        .select_from(Message)
        .where(Message.visitor_session_id == s.id, Message.source == "visitor")
    )
    for r in db.scalars(
        select(AutoReplyRule).where(
            AutoReplyRule.site_id == site.id, AutoReplyRule.enabled.is_(True)
        )
    ):
        t = datetime.now(ZoneInfo(r.timezone))
        h = t.hour
        on_hours = (
            (r.start_hour <= h < r.end_hour)
            if r.start_hour < r.end_hour
            else (h >= r.start_hour or h < r.end_hour)
        )
        workday = (
            (t.weekday() - 1) % 7
            if r.start_hour > r.end_hour and h < r.end_hour
            else t.weekday()
        )
        match = (
            (r.kind == "welcome" and count == 1)
            or (
                r.kind == "keyword"
                and r.keyword
                and r.keyword.casefold() in body.casefold()
            )
            or (r.kind == "offline" and (workday not in r.weekdays or not on_hours))
        )
        fire = db.scalar(
            select(RuleFire).where(
                RuleFire.rule_id == r.id, RuleFire.session_id == s.id
            )
        )
        if not match or (
            fire and (r.kind == "welcome" or now() - fire.fired_at < r.cooldown)
        ):
            continue
        if fire:
            fire.fired_at = now()
        else:
            db.add(RuleFire(rule_id=r.id, session_id=s.id))
        store_message(db, c, conv, s, "auto", r.body)
