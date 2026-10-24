"""定义会话及消息的持久化领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ConversationStatus = Literal["active", "archived", "deleted"]
MessageRole = Literal["user", "assistant", "system", "error"]


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    session_id: str
    title: str
    thread_id: str
    dataset_id: str | None = None
    analysis_id: str | None = None
    report_ids: list[str] = field(default_factory=list)
    status: ConversationStatus = "active"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.title.strip():
            raise ValueError("title is required")
        if not self.thread_id:
            raise ValueError("thread_id is required")
        if self.status not in {"active", "archived", "deleted"}:
            raise ValueError("status must be active, archived, or deleted")
        object.__setattr__(self, "report_ids", list(self.report_ids))


@dataclass(frozen=True)
class ConversationMessage:
    message_id: str
    conversation_id: str
    role: MessageRole
    content: str
    sequence_no: int
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.message_id:
            raise ValueError("message_id is required")
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if self.role not in {"user", "assistant", "system", "error"}:
            raise ValueError("role must be user, assistant, system, or error")
        if not self.content.strip():
            raise ValueError("content is required")
        if self.sequence_no < 1:
            raise ValueError("sequence_no must be positive")
        object.__setattr__(self, "metadata", dict(self.metadata))
