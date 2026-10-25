"""仅初始化管理员；数据库结构由 Alembic 管理。"""

from sqlalchemy import select
from .db import Session
from .models import AdminUser
from .security import passwords
from .config import settings
from cryptography.fernet import Fernet
from urllib.parse import urlsplit


def bootstrap():
    cfg = settings()
    try:
        Fernet(cfg.encryption_key.encode())
    except (ValueError, TypeError):
        raise RuntimeError(
            "ENCRYPTION_KEY 无效，请运行 scripts/generate-env.py 生成配置"
        )
    if cfg.cookie_secure and urlsplit(cfg.public_url).scheme != "https":
        raise RuntimeError("生产 PUBLIC_URL 必须使用 HTTPS")
    if cfg.session_days != 30:
        raise RuntimeError("V1 访客访问凭证有效期固定为 30 天")
    with Session() as db:
        if not db.scalar(select(AdminUser).limit(1)):
            cfg = settings()
            if len(cfg.admin_password) < 12:
                raise RuntimeError("首次启动须设置至少 12 位 ADMIN_PASSWORD")
            db.add(
                AdminUser(
                    username=cfg.admin_username,
                    password_hash=passwords.hash(cfg.admin_password),
                )
            )
            db.commit()


if __name__ == "__main__":
    bootstrap()
