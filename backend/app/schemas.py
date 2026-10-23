import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, EmailStr, field_validator


class SiteInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    domains: list[str] = Field(default_factory=list)
    enabled: bool = True
    color: str = "#2563eb"
    title: str = Field(default="在线客服", max_length=100)
    logo: str = Field(default="", max_length=2000)
    welcome: str = Field(default="您好，请留下邮箱开始咨询。", max_length=4000)
    offline: str = Field(default="我们会尽快回复您。", max_length=4000)

    @field_validator("color")
    @classmethod
    def color_valid(cls, v):
        if not re.fullmatch(r"#[a-fA-F0-9]{6}", v):
            raise ValueError("颜色必须是十六进制")
        return v

    @field_validator("domains")
    @classmethod
    def domains_valid(cls, v):
        for origin in v:
            p = urlsplit(origin)
            if (
                p.scheme not in ("http", "https")
                or not p.hostname
                or p.path
                or p.query
                or p.fragment
                or p.username
            ):
                raise ValueError(
                    "域名须填写完整 Origin，如 https://example.com，不含尾部斜杠"
                )
        return list(set(v))

    @field_validator("logo")
    @classmethod
    def logo_valid(cls, v):
        if v and not v.startswith("https://"):
            raise ValueError("Logo 必须使用 HTTPS 地址")
        return v


class StartInput(BaseModel):
    email: EmailStr


class MessageInput(BaseModel):
    body: str = Field(default="", max_length=12000)
    attachment_id: str | None = None
    client_id: str = Field(min_length=8, max_length=64)


class LoginInput(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=256)


class PasswordInput(BaseModel):
    old_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class QuickInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    category: str = Field(default="常用", max_length=100)
    body: str = Field(min_length=1, max_length=12000)


class RuleInput(BaseModel):
    site_id: str
    kind: str = Field(pattern="^(welcome|offline|keyword)$")
    keyword: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=12000)
    enabled: bool = True
    cooldown: int = Field(default=300, ge=60, le=86400)
    timezone: str = "Asia/Shanghai"
    start_hour: int = Field(default=9, ge=0, le=23)
    end_hour: int = Field(default=18, ge=0, le=23)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])

    @field_validator("timezone")
    @classmethod
    def tz_valid(cls, v):
        try:
            ZoneInfo(v)
        except (KeyError, ValueError):
            raise ValueError("时区无效")
        return v

    @field_validator("weekdays")
    @classmethod
    def days_valid(cls, v):
        if any(x < 0 or x > 6 for x in v):
            raise ValueError("工作日范围 0-6")
        return v


class TelegramInput(BaseModel):
    bot_token: str = Field(default="", max_length=256)
    chat_id: str = Field(pattern=r"^-100[0-9]+$")
    admin_ids: list[int] = Field(min_length=1)
    webhook_secret: str = Field(default="", max_length=256, pattern=r"^[A-Za-z0-9_-]*$")


class BarkInput(BaseModel):
    name: str = Field(default="Bark 设备", max_length=100)
    url: str = Field(max_length=2000)
    enabled: bool = True


class BarkBatch(BaseModel):
    urls: str = Field(max_length=100000)


class ConversationPatch(BaseModel):
    status: str = Field(pattern="^(pending|active|resolved)$")
    notes: str = Field(default="", max_length=20000)
    human_takeover: bool = True


class TopicRepair(BaseModel):
    thread_id: int = Field(gt=0)
    chat_id: str = Field(pattern=r"^-100[0-9]+$")
