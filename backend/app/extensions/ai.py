"""V1 仅定义扩展协议，不调用任何 AI 服务。"""

from typing import Protocol
from dataclasses import dataclass


@dataclass
class ReplyDecision:
    body: str | None = None
    handoff: bool = True


class AIProvider(Protocol):
    async def decide(
        self, context: list[dict], *, human_takeover: bool
    ) -> ReplyDecision: ...


class ContextReader(Protocol):
    def read(self, conversation_id: str, limit: int = 50) -> list[dict]: ...


class SQLContextReader:
    def __init__(self, db):
        self.db = db

    def read(self, conversation_id: str, limit: int = 50) -> list[dict]:
        from sqlalchemy import select
        from ..models import Message
        from ..services import message_dict

        rows = self.db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(min(max(limit, 1), 200))
        )
        return [message_dict(m) for m in reversed(list(rows))]
