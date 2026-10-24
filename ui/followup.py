"""处理分析追问交互，并将 Agent 事件转换为界面状态。"""

from __future__ import annotations

from dataclasses import dataclass

from typing import Any

from agent.agent_setup import reset_agent_thread, stream_agent
from langchain_core.messages import AIMessage, HumanMessage
from storage.analyses import AnalysisStore
from storage.artifacts import ArtifactStore
from storage.conversations import ConversationStore

from .session import AnalysisSession, reset_analysis_thread


def build_followup_prompt(session: AnalysisSession, question: str) -> str:
    if not question or not question.strip():
        raise ValueError("question is required")
    if not session.dataset_id:
        raise ValueError("dataset_id is required for follow-up")
    analysis_id = session.analysis_id or "none"
    return (
        f"当前会话上下文：dataset_id={session.dataset_id}, analysis_id={analysis_id}。\n"
        f"用户追问：{question.strip()}"
    )


def stream_followup(
    runtime: Any,
    session: AnalysisSession,
    question: str,
    *,
    conversation_store: ConversationStore | None = None,
):
    """Stream one follow-up turn and persist durable turn boundaries."""
    prompt = build_followup_prompt(session, question)
    question_text = question.strip()
    if conversation_store is not None:
        if not session.conversation_id:
            raise ValueError("conversation_id is required for persistence")
        history = conversation_store.list_messages(
            session.session_id,
            session.conversation_id,
        )
        conversation_store.append_message(
            session.session_id,
            session.conversation_id,
            role="user",
            content=question_text,
            metadata={"stage": "input"},
        )

    agent_messages = []
    if conversation_store is not None:
        agent_messages.extend(
            HumanMessage(content=message.content)
            if message.role == "user"
            else AIMessage(content=message.content)
            for message in history
            if message.role in {"user", "assistant"}
        )
    agent_messages.append(HumanMessage(content=prompt))

    collected_text: list[str] = []
    try:
        if conversation_store is not None and hasattr(runtime, "checkpointer"):
            reset_agent_thread(runtime, session.thread_id, session.session_id)
        for event in stream_agent(
            runtime,
            agent_messages,
            session.session_id,
            session.thread_id,
        ):
            if getattr(event, "type", None) == "text_delta":
                collected_text.append(str(event.payload.get("delta", "")))
            yield event
    except Exception as exc:
        if conversation_store is not None:
            conversation_store.append_message(
                session.session_id,
                session.conversation_id,
                role="error",
                content=f"追问处理失败：{exc}",
                metadata={"stage": "stream"},
            )
        raise
    else:
        assistant_text = "".join(collected_text).strip()
        if assistant_text and conversation_store is not None:
            conversation_store.append_message(
                session.session_id,
                session.conversation_id,
                role="assistant",
                content=assistant_text,
                metadata={"stage": "completed"},
            )


def reset_followup_ui(state: Any) -> None:
    """Clear only follow-up presentation state, preserving analysis references."""
    state["followup_messages"] = []
    state["followup_events"] = []

def reset_followup_thread(runtime: Any, session: AnalysisSession) -> AnalysisSession:
    if runtime is not None:
        reset_agent_thread(runtime, session.thread_id, session.session_id)
    return reset_analysis_thread(session)


def clear_analysis_data(
    session: AnalysisSession,
    *,
    analysis_store: AnalysisStore,
    artifact_store: ArtifactStore,
) -> None:
    """Delete only explicitly referenced analysis artifacts for this session."""
    for analysis_id in ([session.analysis_id] if session.analysis_id else []):
        analysis_store.delete(session.session_id, analysis_id)
    for artifact_id in session.report_ids:
        artifact_store.delete(session.session_id, artifact_id)



@dataclass(frozen=True)
class FollowUpResponse:
    text: str
    events: list[Any]


def collect_followup_response(events: Any) -> FollowUpResponse:
    collected = list(events)
    text = "".join(
        str(event.payload.get("delta", ""))
        for event in collected
        if getattr(event, "type", None) == "text_delta"
    )
    return FollowUpResponse(text=text, events=collected)


def render_followup_area(
    runtime: Any,
    session: AnalysisSession,
    *,
    conversation_store: ConversationStore | None = None,
) -> FollowUpResponse | None:
    """Render a session-bound follow-up input and stream UIEvents into the chat."""
    st = __import__("streamlit")
    if not session.dataset_id:
        st.info("请先上传并保存数据集，再开始追问")
        return None
    st.subheader("继续探索")
    st.markdown("<div class=\"cb-section-lead\">基于当前数据集与分析结果继续提问，追踪原因、验证假设或寻找下一步行动。</div>", unsafe_allow_html=True)
    question = st.chat_input("围绕当前分析继续提问…", key="analysis_followup")
    if not question:
        return None
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        placeholder = st.empty()
        events = []
        text = ""
        for event in stream_followup(runtime, session, question, conversation_store=conversation_store):
            events.append(event)
            if event.type == "text_delta":
                text += str(event.payload.get("delta", ""))
                placeholder.markdown(text)
        if not text:
            placeholder.info("Agent 未返回文本结果")
    return FollowUpResponse(text=text, events=events)
