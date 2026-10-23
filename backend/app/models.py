import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    Float,
    ForeignKey,
    UniqueConstraint,
    Index,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).timestamp()


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    domains: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str] = mapped_column(String(7), default="#2563eb")
    title: Mapped[str] = mapped_column(String(100), default="在线客服")
    logo: Mapped[str] = mapped_column(Text, default="")
    welcome: Mapped[str] = mapped_column(Text, default="您好，请留下邮箱开始咨询。")
    offline: Mapped[str] = mapped_column(Text, default="我们会尽快回复您。")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("site_id", "email"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[float] = mapped_column(Float, default=now)
    last_seen: Mapped[float] = mapped_column(Float, default=now)
    notes: Mapped[str] = mapped_column(Text, default="")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    unread: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[float] = mapped_column(Float, default=now, index=True)
    human_takeover: Mapped[bool] = mapped_column(Boolean, default=True)


class VisitorSession(Base):
    __tablename__ = "visitor_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[float] = mapped_column(Float, index=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("visitor_session_id", "client_id"),
        Index("ix_messages_conv_time", "conversation_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    visitor_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("visitor_sessions.id"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text, default="")
    attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("attachments.id"), nullable=True
    )
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_key: Mapped[str | None] = mapped_column(
        String(160), unique=True, nullable=True
    )
    created_at: Mapped[float] = mapped_column(Float, default=now)
    status: Mapped[str] = mapped_column(String(30), default="stored")


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    visitor_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("visitor_sessions.id"), nullable=True
    )
    path: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(40), default="image/png")


class TelegramTopic(Base):
    __tablename__ = "telegram_topics"
    __table_args__ = (UniqueConstraint("chat_id", "thread_id"),)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id"), primary_key=True
    )
    chat_id: Mapped[str] = mapped_column(String(40))
    thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")


class BarkDevice(Base):
    __tablename__ = "bark_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    url_encrypted: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class QuickReply(Base):
    __tablename__ = "quick_replies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100), default="常用")
    body: Mapped[str] = mapped_column(Text)


class AutoReplyRule(Base):
    __tablename__ = "auto_reply_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    keyword: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown: Mapped[int] = mapped_column(Integer, default=300)
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Shanghai")
    start_hour: Mapped[int] = mapped_column(Integer, default=9)
    end_hour: Mapped[int] = mapped_column(Integer, default=18)
    weekdays: Mapped[list] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])


class RuleFire(Base):
    __tablename__ = "rule_fires"
    __table_args__ = (UniqueConstraint("rule_id", "session_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    rule_id: Mapped[str] = mapped_column(ForeignKey("auto_reply_rules.id"))
    session_id: Mapped[str] = mapped_column(ForeignKey("visitor_sessions.id"))
    fired_at: Mapped[float] = mapped_column(Float, default=now)


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="owner")


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"))
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ip: Mapped[str] = mapped_column(String(100), index=True)
    created_at: Mapped[float] = mapped_column(Float, default=now, index=True)


class Delivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index("ix_delivery_due", "status", "next_attempt"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=now)
    error: Mapped[str] = mapped_column(Text, default="")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    sent_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"
    update_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
