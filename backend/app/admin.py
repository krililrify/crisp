import re
from fastapi import (
    APIRouter,
    Depends,
    Request,
    Response,
    HTTPException,
    UploadFile,
    File,
)
from sqlalchemy import select, func, or_, delete
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from .db import db_session
from .config import settings
from .models import *
from .security import *
from .schemas import *
from .services import *
from .integrations import tg, telegram_config, ExternalError
from .uploads import save_image

router = APIRouter(prefix="/api/admin")


def require(request: Request, db=Depends(db_session)):
    admin_auth(request, db, request.method not in ("GET", "HEAD"))
    return db


@router.post("/login")
def login(
    data: LoginInput, request: Request, response: Response, db=Depends(db_session)
):
    if request.headers.get("origin") != settings().public_url.rstrip("/"):
        raise HTTPException(403, "来源不合法")
    ip = request.client.host if request.client else "unknown"
    n = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.ip == ip, LoginAttempt.created_at > now() - 900)
    )
    if n >= 10:
        raise HTTPException(429, "登录尝试过多，请 15 分钟后再试")
    db.add(LoginAttempt(ip=ip))
    db.commit()
    u = db.scalar(select(AdminUser).where(AdminUser.username == data.username))
    try:
        if not u:
            passwords.verify(passwords.hash("invalid-password-dummy"), data.password)
            raise VerifyMismatchError()
        passwords.verify(u.password_hash, data.password)
    except (VerifyMismatchError, InvalidHashError):
        raise HTTPException(401, "账号或密码错误")
    raw = token()
    csrf = token()
    db.add(
        AdminSession(
            token_hash=digest(raw),
            user_id=u.id,
            csrf=csrf,
            expires_at=now() + 12 * 3600,
        )
    )
    db.commit()
    response.set_cookie(
        "support_admin",
        raw,
        max_age=12 * 3600,
        secure=settings().cookie_secure,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return {"csrf": csrf, "username": u.username}


@router.get("/me")
def me(request: Request, db=Depends(require)):
    s = admin_auth(request, db)
    u = db.get(AdminUser, s.user_id)
    return {"username": u.username, "csrf": s.csrf}


@router.post("/logout")
def logout(request: Request, response: Response, db=Depends(require)):
    s = admin_auth(request, db)
    db.delete(s)
    db.commit()
    response.delete_cookie("support_admin", path="/")
    return {"ok": True}


@router.post("/password")
def password(
    data: PasswordInput, request: Request, response: Response, db=Depends(require)
):
    s = admin_auth(request, db)
    u = db.get(AdminUser, s.user_id)
    try:
        passwords.verify(u.password_hash, data.old_password)
    except VerifyMismatchError:
        raise HTTPException(403, "原密码错误")
    u.password_hash = passwords.hash(data.new_password)
    db.execute(delete(AdminSession).where(AdminSession.user_id == u.id))
    db.commit()
    response.delete_cookie("support_admin", path="/")
    return {"ok": True}


@router.get("/sites")
def sites(db=Depends(require)):
    return list(db.scalars(select(Site).order_by(Site.name)))


@router.post("/sites")
def create_site(data: SiteInput, db=Depends(require)):
    site = Site(**data.model_dump())
    db.add(site)
    db.commit()
    return site


@router.put("/sites/{ident}")
def edit_site(ident: str, data: SiteInput, db=Depends(require)):
    site = db.get(Site, ident)
    if not site:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(site, k, v)
    db.commit()
    return site


@router.get("/conversations")
def conversations(
    site_id: str = "",
    q: str = "",
    status: str = "",
    since: float | None = None,
    until: float | None = None,
    offset: int = 0,
    db=Depends(require),
):
    query = (
        select(Conversation, Customer, Site)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(Site, Site.id == Customer.site_id)
    )
    if site_id:
        query = query.where(Site.id == site_id)
    if status:
        query = query.where(Conversation.status == status)
    if q:
        query = query.where(
            or_(
                Customer.email.icontains(q, autoescape=True),
                Conversation.id.in_(
                    select(Message.conversation_id).where(
                        Message.body.icontains(q, autoescape=True)
                    )
                ),
            )
        )
    if since is not None or until is not None:
        mq = select(Message.conversation_id)
        if since is not None:
            mq = mq.where(Message.created_at >= since)
        if until is not None:
            mq = mq.where(Message.created_at <= until)
        query = query.where(Conversation.id.in_(mq))
    return [
        dict(
            id=v.id,
            customer_id=c.id,
            email=c.email,
            site_id=s.id,
            site_name=s.name,
            status=v.status,
            unread=v.unread,
            updated_at=v.updated_at,
            notes=c.notes,
            first_seen=c.created_at,
            last_seen=c.last_seen,
            human_takeover=v.human_takeover,
        )
        for v, c, s in db.execute(
            query.order_by(Conversation.updated_at.desc())
            .offset(max(0, offset))
            .limit(100)
        )
    ]


def conv_lookup(db, ident):
    v = db.get(Conversation, ident)
    if not v:
        raise HTTPException(404)
    return v, db.get(Customer, v.customer_id)


@router.get("/conversations/{ident}")
def conversation(ident: str, db=Depends(require)):
    v, c = conv_lookup(db, ident)
    site = db.get(Site, c.site_id)
    return dict(
        id=v.id,
        customer_id=c.id,
        email=c.email,
        site_id=c.site_id,
        site_name=site.name,
        status=v.status,
        notes=c.notes,
        first_seen=c.created_at,
        last_seen=c.last_seen,
        human_takeover=v.human_takeover,
    )


@router.get("/conversations/{ident}/messages")
def conv_messages(ident: str, before: float | None = None, db=Depends(require)):
    v, c = conv_lookup(db, ident)
    query = select(Message).where(Message.conversation_id == ident)
    if before:
        query = query.where(Message.created_at < before)
    return [
        message_dict(m)
        for m in reversed(
            list(
                db.scalars(
                    query.order_by(Message.created_at.desc(), Message.id.desc()).limit(
                        100
                    )
                )
            )
        )
    ]


@router.post("/conversations/{ident}/read")
def mark_read(ident: str, db=Depends(require)):
    v, c = conv_lookup(db, ident)
    v.unread = 0
    db.commit()
    return {"ok": True}


@router.patch("/conversations/{ident}")
def edit_conv(ident: str, data: ConversationPatch, db=Depends(require)):
    v, c = conv_lookup(db, ident)
    v.status = data.status
    v.human_takeover = data.human_takeover
    c.notes = data.notes
    enqueue(
        db,
        "topic_state",
        {"customer_id": c.id, "closed": v.status == "resolved"},
        "state:" + uid(),
    )
    db.commit()
    return {"ok": True}


@router.post("/conversations/{ident}/messages")
def reply(ident: str, data: MessageInput, db=Depends(require)):
    v, c = conv_lookup(db, ident)
    db.scalar(select(Conversation).where(Conversation.id == ident).with_for_update())
    m = store_message(
        db,
        c,
        v,
        current_session(db, c.id),
        "admin",
        data.body,
        data.attachment_id,
        data.client_id,
    )
    v.status = "active"
    db.commit()
    return message_dict(m)


@router.post("/conversations/{ident}/uploads")
async def upload(ident: str, file: UploadFile = File(...), db=Depends(require)):
    v, c = conv_lookup(db, ident)
    s = current_session(db, c.id)
    a = save_image(
        db, await file.read(settings().max_upload_bytes + 1), c.id, s.id if s else None
    )
    db.commit()
    return {"id": a.id}


@router.get("/quick-replies")
def quick_list(db=Depends(require)):
    return list(
        db.scalars(select(QuickReply).order_by(QuickReply.category, QuickReply.title))
    )


@router.post("/quick-replies")
def quick_add(data: QuickInput, db=Depends(require)):
    q = QuickReply(**data.model_dump())
    db.add(q)
    db.commit()
    return q


@router.put("/quick-replies/{ident}")
def quick_edit(ident: str, data: QuickInput, db=Depends(require)):
    q = db.get(QuickReply, ident)
    if not q:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(q, k, v)
    db.commit()
    return q


@router.delete("/quick-replies/{ident}")
def quick_delete(ident: str, db=Depends(require)):
    q = db.get(QuickReply, ident)
    if not q:
        raise HTTPException(404)
    db.delete(q)
    db.commit()
    return {"ok": True}


@router.get("/rules")
def rules(site_id: str = "", db=Depends(require)):
    q = select(AutoReplyRule)
    if site_id:
        q = q.where(AutoReplyRule.site_id == site_id)
    return list(db.scalars(q))


@router.post("/rules")
def rule_add(data: RuleInput, db=Depends(require)):
    if not db.get(Site, data.site_id):
        raise HTTPException(404)
    q = AutoReplyRule(**data.model_dump())
    db.add(q)
    db.commit()
    return q


@router.put("/rules/{ident}")
def rule_edit(ident: str, data: RuleInput, db=Depends(require)):
    q = db.get(AutoReplyRule, ident)
    if not q or not db.get(Site, data.site_id):
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(q, k, v)
    db.commit()
    return q


@router.delete("/rules/{ident}")
def rule_delete(ident: str, db=Depends(require)):
    q = db.get(AutoReplyRule, ident)
    if not q:
        raise HTTPException(404)
    db.execute(delete(RuleFire).where(RuleFire.rule_id == ident))
    db.delete(q)
    db.commit()
    return {"ok": True}


@router.get("/telegram")
def telegram_get(db=Depends(require)):
    c = setting(db, "telegram")
    return {
        "configured": bool(c.get("token")),
        "chat_id": c.get("chat_id", ""),
        "admin_ids": c.get("admin_ids", []),
    }


@router.put("/telegram")
def telegram_save(data: TelegramInput, db=Depends(require)):
    old = setting(db, "telegram")
    if not old.get("token") and not data.bot_token:
        raise HTTPException(422, "首次配置需要 Token")
    c = {
        "token": encrypt(data.bot_token) if data.bot_token else old["token"],
        "secret": (encrypt(data.webhook_secret) if data.webhook_secret else old.get("secret") or encrypt(token())),
        "chat_id": data.chat_id,
        "admin_ids": data.admin_ids,
    }
    put_setting(db, "telegram", c)
    db.commit()
    try:
        cfg = telegram_config(db)
        tg(db, "setWebhook", {"url": settings().public_url + "/api/telegram/webhook", "secret_token": cfg["secret"], "allowed_updates": ["message"]})
    except ExternalError as exc:
        return {"ok": True, "webhook_registered": False, "warning": "配置已保存，但 Webhook 注册失败，请重试注册：" + str(exc)}
    return {"ok": True, "webhook_registered": True}


@router.post("/telegram/test")
def telegram_test(db=Depends(require)):
    try:
        cfg = telegram_config(db)
        bot = tg(db, "getMe")
        chat = tg(db, "getChat", {"chat_id": cfg["chat_id"]})
        member = tg(
            db, "getChatMember", {"chat_id": cfg["chat_id"], "user_id": bot["id"]}
        )
        return {
            "bot": bot.get("username"),
            "is_forum": chat.get("is_forum", False),
            "can_manage_topics": member.get("can_manage_topics", False),
        }
    except ExternalError as e:
        raise HTTPException(502, str(e))


@router.post("/telegram/webhook")
def telegram_set_webhook(db=Depends(require)):
    try:
        cfg = telegram_config(db)
        return tg(
            db,
            "setWebhook",
            {
                "url": settings().public_url + "/api/telegram/webhook",
                "secret_token": cfg["secret"],
                "allowed_updates": ["message"],
            },
        )
    except ExternalError as e:
        raise HTTPException(502, str(e))


@router.get("/topics")
def topics(db=Depends(require)):
    return [
        dict(
            customer_id=t.customer_id,
            chat_id=t.chat_id,
            thread_id=t.thread_id,
            error=t.error,
            closed=t.closed,
            email=c.email,
            site_id=c.site_id,
        )
        for t, c in db.execute(
            select(TelegramTopic, Customer).join(
                Customer, Customer.id == TelegramTopic.customer_id
            )
        )
    ]


@router.put("/topics/{customer_id}")
def topic_repair(customer_id: str, data: TopicRepair, db=Depends(require)):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404)
    duplicate = db.scalar(
        select(TelegramTopic).where(
            TelegramTopic.chat_id == data.chat_id,
            TelegramTopic.thread_id == data.thread_id,
            TelegramTopic.customer_id != customer_id,
        )
    )
    if duplicate:
        raise HTTPException(409, "话题已绑定其他客户")
    t = db.get(TelegramTopic, customer_id)
    if not t:
        t = TelegramTopic(customer_id=customer_id, chat_id=data.chat_id)
        db.add(t)
    t.chat_id = data.chat_id
    t.thread_id = data.thread_id
    t.error = ""
    db.commit()
    return {"ok": True}


@router.get("/bark")
def bark_list(db=Depends(require)):
    return {
        "enabled": setting(db, "bark", {"enabled": True}).get("enabled", True),
        "devices": [
            {
                "id": d.id,
                "name": d.name,
                "enabled": d.enabled,
                "url_hint": "••••••（已加密保存）",
            }
            for d in db.scalars(select(BarkDevice))
        ],
    }


@router.put("/bark")
def bark_global(enabled: bool, db=Depends(require)):
    put_setting(db, "bark", {"enabled": enabled})
    db.commit()
    return {"ok": True}


@router.post("/bark/devices")
def bark_add(data: BarkInput, db=Depends(require)):
    url = validate_url(data.url)
    if db.scalar(select(BarkDevice).where(BarkDevice.url_hash == digest(url))):
        raise HTTPException(409, "设备已存在")
    d = BarkDevice(
        name=data.name,
        enabled=data.enabled,
        url_encrypted=encrypt(url),
        url_hash=digest(url),
    )
    db.add(d)
    db.commit()
    return {"id": d.id}


@router.post("/bark/batch")
def bark_batch(data: BarkBatch, db=Depends(require)):
    urls = [validate_url(u.strip()) for u in re.split("[,\n]", data.urls) if u.strip()]
    added = 0
    for url in dict.fromkeys(urls):
        if db.scalar(select(BarkDevice).where(BarkDevice.url_hash == digest(url))):
            continue
        db.add(
            BarkDevice(
                name=f"设备 {added + 1}",
                url_encrypted=encrypt(url),
                url_hash=digest(url),
            )
        )
        added += 1
    db.commit()
    return {"added": added}


@router.put("/bark/devices/{ident}")
def bark_edit(ident: str, data: BarkInput, db=Depends(require)):
    d = db.get(BarkDevice, ident)
    if not d:
        raise HTTPException(404)
    d.name = data.name
    d.enabled = data.enabled
    if data.url:
        url = validate_url(data.url)
        other = db.scalar(
            select(BarkDevice).where(
                BarkDevice.url_hash == digest(url), BarkDevice.id != ident
            )
        )
        if other:
            raise HTTPException(409, "设备已存在")
        d.url_encrypted = encrypt(url)
        d.url_hash = digest(url)
    db.commit()
    return {"ok": True}


@router.delete("/bark/devices/{ident}")
def bark_delete(ident: str, db=Depends(require)):
    d = db.get(BarkDevice, ident)
    if not d:
        raise HTTPException(404)
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.post("/bark/test")
def bark_test(device_id: str = "", db=Depends(require)):
    query = select(BarkDevice).where(BarkDevice.enabled.is_(True))
    if device_id:
        query = query.where(BarkDevice.id == device_id)
    ids = []
    for d in db.scalars(query):
        key = "test:" + uid()
        enqueue(db, "bark", {"device_id": d.id, "test": True}, key)
        ids.append(key)
    db.commit()
    return {"queued": ids, "note": "结果请在投递日志查看；API 接受不等于设备收到。"}


@router.get("/deliveries")
def deliveries(offset: int = 0, db=Depends(require)):
    return [
        dict(
            id=t.id,
            kind=t.kind,
            status=t.status,
            attempts=t.attempts,
            error=t.error,
            http_status=t.http_status,
            created_at=t.created_at,
            sent_at=t.sent_at,
            next_attempt=t.next_attempt,
            device_name=(
                db.get(BarkDevice, t.payload.get("device_id")).name
                if t.kind == "bark" and db.get(BarkDevice, t.payload.get("device_id"))
                else None
            ),
        )
        for t in db.scalars(
            select(Delivery)
            .order_by(Delivery.created_at.desc())
            .offset(max(offset, 0))
            .limit(100)
        )
    ]


@router.post("/deliveries/{ident}/retry")
def delivery_retry(ident: str, db=Depends(require)):
    t = db.get(Delivery, ident)
    if not t:
        raise HTTPException(404)
    if t.status == "working":
        raise HTTPException(409, "任务正在执行")
    if t.status == "sent":
        raise HTTPException(409, "已成功的任务不重复执行")
    t.status = "pending"
    t.attempts = 0
    t.next_attempt = now()
    db.commit()
    return {"ok": True}
