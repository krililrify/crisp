import asyncio, secrets
from pathlib import Path
from fastapi import (
    FastAPI,
    Request,
    Depends,
    HTTPException,
    UploadFile,
    File,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import Session, db_session
from .models import *
from .security import *
from .schemas import *
from .services import *
from .uploads import save_image
from .admin import router as admin_router

app = FastAPI(title="自托管在线客服", version="1.0.0", docs_url=None, redoc_url=None)
app.include_router(admin_router)


@app.middleware("http")
async def security_headers(request, call_next):
    # Reject large bodies before multipart parsing. Caddy also enforces this limit.
    length = request.headers.get("content-length")
    if length and (
        not length.isdigit() or int(length) > settings().max_upload_bytes + 65536
    ):
        return JSONResponse({"detail": "请求过大"}, 413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: https:; connect-src 'self' ws: wss:; object-src 'none'; base-uri 'none'; form-action 'self'"
    )
    if request.url.path.startswith("/admin") or request.url.path.startswith(
        "/api/admin"
    ):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] += "; frame-ancestors 'none'"
    if request.url.path == "/widget.js":
        response.headers["Access-Control-Allow-Origin"] = "*"
    return response


def get_site(db, ident):
    site = db.get(Site, ident)
    if not site or not site.enabled:
        raise HTTPException(404, "网站不存在或已禁用")
    return site


def visitor(request, db, site_id):
    authorization = request.headers.get("authorization", "")
    return visitor_auth(db, site_id, authorization.removeprefix("Bearer "))


@app.get("/health")
def health(db=Depends(db_session)):
    db.execute(select(1))
    return {"ok": True}


@app.get("/api/sites/{site_id}/public")
def public(site_id: str, db=Depends(db_session)):
    s = get_site(db, site_id)
    return {
        k: getattr(s, k)
        for k in (
            "id",
            "name",
            "title",
            "color",
            "logo",
            "welcome",
            "offline",
            "domains",
            "subtitle",
            "welcome_heading",
            "welcome_icon",
            "business_hours",
            "problem_prompt",

        )
    }


@app.post("/api/sites/{site_id}/sessions")
def start(site_id: str, data: StartInput, request: Request, db=Depends(db_session)):
    site = get_site(db, site_id)
    if not origin_allowed(site, request.headers.get("origin")):
        raise HTTPException(403, "来源不合法")
    ip = "visitor:" + digest(request.client.host if request.client else "unknown")
    recent = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.ip == ip, LoginAttempt.created_at > now() - 900)
    )
    if recent >= 15:
        raise HTTPException(429, "创建会话过于频繁，请稍后重试")
    db.add(LoginAttempt(ip=ip))
    db.flush()
    # Row lock serializes first contact per site; unique constraints are the final guard.
    db.scalar(select(Site).where(Site.id == site_id).with_for_update())
    email = str(data.email).strip().casefold()
    c = db.scalar(
        select(Customer).where(Customer.site_id == site_id, Customer.email == email)
    )
    if not c:
        c = Customer(site_id=site_id, email=email)
        db.add(c)
        db.flush()
        conv = Conversation(customer_id=c.id)
        db.add(conv)
        db.flush()
    else:
        conv = db.scalar(select(Conversation).where(Conversation.customer_id == c.id))
    raw = token()
    expires = now() + settings().session_days * 86400
    s = VisitorSession(customer_id=c.id, token_hash=digest(raw), expires_at=expires)
    db.add(s)
    db.flush()
    if data.problem:
        store_message(db, c, conv, s, "visitor", data.problem, client_id="initial:" + s.id)
        apply_rules(db, site, c, conv, s, data.problem)
    db.commit()
    return {
        "email": email,
        "token": raw,
        "expires_at": expires,
        "conversation_id": conv.id,
        "session_id": s.id,
    }


@app.get("/api/sites/{site_id}/me")
def visitor_profile(site_id: str, request: Request, db=Depends(db_session)):
    s, c = visitor(request, db, site_id)
    return {"email": c.email}


@app.get("/api/sites/{site_id}/messages")
def history(
    site_id: str, request: Request, before: float | None = None, db=Depends(db_session)
):
    s, c = visitor(request, db, site_id)
    q = select(Message).where(Message.visitor_session_id == s.id)
    if before:
        q = q.where(Message.created_at < before)
    items = list(
        db.scalars(q.order_by(Message.created_at.desc(), Message.id.desc()).limit(100))
    )
    return [message_dict(m) for m in reversed(items)]


@app.post("/api/sites/{site_id}/messages")
def send(site_id: str, data: MessageInput, request: Request, db=Depends(db_session)):
    s, c = visitor(request, db, site_id)
    conv = db.scalar(
        select(Conversation).where(Conversation.customer_id == c.id).with_for_update()
    )
    existing = db.scalar(
        select(Message).where(
            Message.visitor_session_id == s.id,
            Message.client_id == data.client_id,
            Message.source == "visitor",
        )
    )
    if existing:
        return message_dict(existing)
    recent = db.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.visitor_session_id == s.id,
            Message.source == "visitor",
            Message.created_at > now() - 60,
        )
    )
    if recent >= 30:
        raise HTTPException(429, "发送太快，请稍后再试")
    m = store_message(
        db, c, conv, s, "visitor", data.body, data.attachment_id, data.client_id
    )
    apply_rules(db, db.get(Site, c.site_id), c, conv, s, data.body)
    db.commit()
    return message_dict(m)


@app.post("/api/sites/{site_id}/uploads")
async def upload(
    site_id: str, request: Request, file: UploadFile = File(...), db=Depends(db_session)
):
    s, c = visitor(request, db, site_id)
    a = save_image(db, await file.read(settings().max_upload_bytes + 1), c.id, s.id)
    db.commit()
    return {"id": a.id}


@app.get("/api/attachments/{ident}")
def attachment(ident: str, request: Request, site_id: str = "", db=Depends(db_session)):
    a = db.get(Attachment, ident)
    if not a:
        raise HTTPException(404)
    if request.cookies.get("support_admin"):
        admin_auth(request, db)
    else:
        s, c = visitor(request, db, site_id)
        if a.customer_id != c.id or a.visitor_session_id != s.id:
            raise HTTPException(403)
    return FileResponse(
        a.path, media_type=a.mime, headers={"Cache-Control": "private, no-store"}
    )


@app.post("/api/telegram/webhook")
async def webhook(request: Request, db=Depends(db_session)):
    cfg = setting(db, "telegram")
    expected = decrypt(cfg["secret"]) if cfg.get("secret") else ""
    if not expected or not secrets.compare_digest(
        expected, request.headers.get("x-telegram-bot-api-secret-token", "")
    ):
        raise HTTPException(403)
    if int(request.headers.get("content-length", "0")) > 100000:
        raise HTTPException(413)
    try:
        payload = await request.json()
        update_id = payload["update_id"]
        if not isinstance(update_id, int):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, "更新格式无效")
    try:
        enqueue(db, "telegram_update", payload, "update:" + str(update_id))
        db.commit()
    except IntegrityError:
        db.rollback()  # Telegram retries are acknowledged only after durable persistence.
    return {"ok": True}


@app.websocket("/api/ws")
async def realtime(ws: WebSocket):
    await ws.accept()
    try:
        auth = await asyncio.wait_for(ws.receive_json(), 10)
        if not isinstance(auth, dict) or auth.get("role") not in ("admin", "visitor"):
            await ws.close(4401)
            return
        role = auth.get("role")
        site_id = auth.get("site_id", "")
        raw = auth.get("token", "")
        if (
            not isinstance(raw, str)
            or not isinstance(site_id, str)
            or len(raw) > 100
            or len(site_id) > 36
        ):
            await ws.close(4401)
            return
        origin = ws.headers.get("origin")
        with Session() as db:
            if role == "admin":
                s = db.get(AdminSession, digest(ws.cookies.get("support_admin", "")))
                if (
                    not s
                    or s.expires_at <= now()
                    or origin != settings().public_url.rstrip("/")
                ):
                    await ws.close(4401)
                    return
                expires = s.expires_at
                session_hash = s.token_hash
            else:
                vs, c = visitor_auth(db, site_id, raw)
                if origin != settings().public_url.rstrip("/"):
                    await ws.close(4403)
                    return
                expires = vs.expires_at
                session_hash = vs.token_hash
        last = None
        while True:
            with Session() as db:
                if expires <= now():
                    await ws.close(4401)
                    return
                if role == "admin":
                    if not db.get(AdminSession, session_hash):
                        await ws.close(4401)
                        return
                    # Revision signal; REST returns only requested pages.
                    revision = db.execute(
                        select(func.count(Message.id), func.max(Message.created_at))
                    ).one()
                    counts = db.scalar(select(func.sum(Conversation.unread))) or 0
                    revision = (*revision, counts)
                else:
                    vs, c = visitor_auth(db, site_id, raw)
                    revision = db.execute(
                        select(
                            func.count(Message.id), func.max(Message.created_at)
                        ).where(Message.visitor_session_id == vs.id)
                    ).one()
                if tuple(revision) != last:
                    await ws.send_json({"type": "changed"})
                    last = tuple(revision)
            # Receive disconnect events even when no messages are changing.
            # Otherwise idle closed sockets leak tasks and block graceful shutdown.
            try:
                event = await asyncio.wait_for(ws.receive(), timeout=1)
                if event["type"] == "websocket.disconnect":
                    return
            except asyncio.TimeoutError:
                continue
    except (
        WebSocketDisconnect,
        asyncio.TimeoutError,
        HTTPException,
        ValueError,
        TypeError,
    ):
        try:
            await ws.close(4401)
        except RuntimeError:
            pass


static = Path(__file__).parent / "static"
if static.exists():

    @app.get("/widget.js")
    def widget():
        return FileResponse(static / "widget.js", media_type="application/javascript")

    app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/admin/{path:path}")
    @app.get("/chat/{path:path}")
    def frontend(path: str = ""):
        return FileResponse(static / "index.html")
