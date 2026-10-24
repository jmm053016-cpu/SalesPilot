"""集中管理 Streamlit 会话状态及其默认初始化规则。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from uuid import uuid4

from models.conversation import Conversation


@dataclass(frozen=True)
class AnalysisSession:
    session_id: str
    conversation_id: str | None = None
    dataset_id: str | None = None
    analysis_id: str | None = None
    report_ids: list[str] = field(default_factory=list)
    thread_id: str = field(default_factory=lambda: f"thread_{uuid4().hex}")


def create_analysis_session(
    session_id: str,
    conversation_id: str | None = None,
) -> AnalysisSession:
    if not session_id:
        raise ValueError("session_id is required")
    return AnalysisSession(
        session_id=session_id,
        conversation_id=conversation_id,
    )


def new_conversation_session(
    session_id: str,
    conversation: Conversation,
) -> AnalysisSession:
    if not session_id:
        raise ValueError("session_id is required")
    if conversation.session_id != session_id:
        raise ValueError("conversation does not belong to session")
    return AnalysisSession(
        session_id=session_id,
        conversation_id=conversation.conversation_id,
        thread_id=conversation.thread_id,
    )


def session_from_conversation(conversation: Conversation) -> AnalysisSession:
    return AnalysisSession(
        session_id=conversation.session_id,
        conversation_id=conversation.conversation_id,
        dataset_id=conversation.dataset_id,
        analysis_id=conversation.analysis_id,
        report_ids=list(conversation.report_ids),
        thread_id=conversation.thread_id,
    )


def session_to_resource_binding(session: AnalysisSession) -> dict[str, object]:
    return {
        "dataset_id": session.dataset_id,
        "analysis_id": session.analysis_id,
        "report_ids": list(session.report_ids),
        "thread_id": session.thread_id,
    }


def reset_analysis_thread(session: AnalysisSession) -> AnalysisSession:
    return replace(session, thread_id=f"thread_{uuid4().hex}")


def artifact_download_ref(*, artifact_id: str, display_name: str, mime_type: str) -> dict[str, str]:
    return {
        "artifact_id": artifact_id,
        "display_name": display_name,
        "mime_type": mime_type,
    }
