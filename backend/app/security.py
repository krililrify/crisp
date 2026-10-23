import hashlib, secrets, re
from urllib.parse import urlsplit
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from sqlalchemy import select
from markdown_it import MarkdownIt
import bleach
from .config import settings
from .models import AdminSession, VisitorSession, Customer, Site, now

passwords = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()


def token():
    return secrets.token_urlsafe(32)


def encrypt(s):
    return Fernet(settings().encryption_key.encode()).encrypt(s.encode()).decode()


def decrypt(s):
    return Fernet(settings().encryption_key.encode()).decrypt(s.encode()).decode()


def admin_auth(request: Request, db, write=False):
    raw = request.cookies.get("support_admin", "")
    s = db.get(AdminSession, digest(raw))
    if not s or s.expires_at <= now():
        raise HTTPException(401, "请登录")
    if write:
        if request.headers.get("origin") != settings().public_url.rstrip("/"):
            raise HTTPException(403, "来源不合法")
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), s.csrf):
            raise HTTPException(403, "CSRF 验证失败")
    return s


def visitor_auth(db, site_id, raw):
    s = db.scalar(
        select(VisitorSession).where(VisitorSession.token_hash == digest(raw or ""))
    )
    if not s or s.expires_at <= now():
        raise HTTPException(401, "访问凭证已过期，请重新填写邮箱")
    c = db.get(Customer, s.customer_id)
    site = db.get(Site, c.site_id)
    if c.site_id != site_id or not site.enabled:
        raise HTTPException(403, "站点访问被拒绝")
    return s, c


def origin_allowed(site, origin):
    return origin == settings().public_url.rstrip("/") or origin in site.domains


def validate_url(url):
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or not p.hostname
        or p.username
        or p.password
        or p.query
        or p.fragment
    ):
        raise HTTPException(422, "请使用无参数的 HTTPS Bark 设备地址")
    try:
        port = p.port
    except ValueError:
        raise HTTPException(422, "Bark 端口无效")
    if p.hostname not in settings().bark_allowed_hosts.split(",") or port not in (
        None,
        443,
    ):
        raise HTTPException(422, "Bark 域名不在服务端允许列表")
    if not p.path.strip("/") or len(p.path.strip("/").split("/")) != 1:
        raise HTTPException(422, "Bark 地址格式为 https://服务器/设备密钥")
    return url.rstrip("/")


md = MarkdownIt("commonmark", {"html": False, "linkify": False})


def render(text):
    html = bleach.clean(
        md.render(text),
        tags={
            "p",
            "br",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "strong",
            "em",
            "a",
            "ul",
            "ol",
            "li",
            "code",
            "pre",
            "blockquote",
            "img",
            "hr",
        },
        attributes={"a": ["href", "title"], "img": ["src", "alt", "title"]},
        protocols={"https", "http"},
        strip=True,
    )
    # Restrict external pictures to HTTPS; protected relative uploads are rendered separately.
    html = re.sub(r'<img[^>]+src="(?!https://)[^"]*"[^>]*>', "", html)
    return html.replace("<a ", '<a target="_blank" rel="noopener noreferrer nofollow" ')
