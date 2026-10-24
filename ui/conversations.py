"""渲染会话列表与会话生命周期操作，并同步持久化状态。"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from models.conversation import Conversation, ConversationMessage
from storage.conversations import ConversationStore
from utils.logging_config import get_logger

from .session import AnalysisSession, session_from_conversation

_DEFAULT_TITLE = "新建会话"
_MAX_TITLE_LENGTH = 32
logger = get_logger(__name__)


def derive_conversation_title(question: str) -> str:
    """Derive a short deterministic title from the first user question."""
    first_line = next((line.strip() for line in question.splitlines() if line.strip()), "")
    if not first_line:
        return _DEFAULT_TITLE
    if len(first_line) <= _MAX_TITLE_LENGTH:
        return first_line
    return f"{first_line[:_MAX_TITLE_LENGTH - 1].rstrip()}…"


def create_new_conversation(
    store: ConversationStore,
    session_id: str,
    *,
    question: str = "",
) -> Conversation:
    conversation = store.create(session_id, title=derive_conversation_title(question))
    logger.info("conversation.create.requested | 用户请求创建会话 | 会话ID=%s | 状态=%s", conversation.conversation_id, conversation.status)
    return conversation


def can_continue(conversation: Conversation, dataset_exists: bool) -> bool:
    """Whether a historical conversation can accept a new follow-up."""
    return (
        conversation.status == "active"
        and bool(conversation.dataset_id)
        and dataset_exists
    )


def switch_conversation(
    store: ConversationStore,
    session_id: str,
    conversation_id: str,
) -> AnalysisSession:
    try:
        conversation = store.get(session_id, conversation_id)
        if conversation is None:
            raise LookupError("conversation not found")
        if conversation.status not in {"active", "archived"}:
            raise PermissionError("conversation is not available")
        session = session_from_conversation(conversation)
    except Exception as exc:
        logger.warning("conversation.switched.failed | 切换会话失败 | 会话ID=%s | 异常类型=%s", conversation_id, type(exc).__name__)
        raise
    logger.info("conversation.switched | 会话切换完成 | 会话ID=%s | 状态=%s", conversation_id, conversation.status)
    return session


def reset_conversation_view_state(state: Any) -> None:
    """Clear page-local results when changing the active conversation."""
    state["followup_messages"] = []
    state["followup_events"] = []
    state["analysis_result"] = None
    state["analysis_report"] = None


def render_conversation_messages(messages: list[ConversationMessage]) -> None:
    st = __import__("streamlit")
    for message in messages:
        with st.chat_message(message.role):
            st.markdown(message.content)


def render_conversation_sidebar(
    store: ConversationStore,
    session_id: str,
    current_id: str | None,
) -> str | None:
    """Render searchable history navigation and return the selected conversation ID."""
    st = __import__("streamlit")
    conversations = store.list_all_history()
    st.markdown('<div class="cb-sidebar-section-title">历史会话</div>', unsafe_allow_html=True)
    if st.button(
        "新建会话",
        type="primary",
        use_container_width=True,
        key="new_conversation",
    ):
        conversation = create_new_conversation(store, session_id)
        return conversation.conversation_id

    query = st.text_input(
        "搜索会话",
        value="",
        placeholder="搜索历史会话",
        label_visibility="collapsed",
        key="conversation_search",
    ).strip().casefold()
    matches = [
        conversation
        for conversation in conversations
        if not query or query in conversation.title.casefold()
    ]
    active = [conversation for conversation in matches if conversation.status == "active"]
    archived = [conversation for conversation in matches if conversation.status == "archived"]

    if not conversations:
        st.markdown('<div class="cb-sidebar-empty">还没有历史会话</div>', unsafe_allow_html=True)
        return None
    if not matches:
        st.markdown('<div class="cb-sidebar-empty">没有匹配的会话</div>', unsafe_allow_html=True)

    for conversation in active:
        if st.button(
            conversation.title,
            key=f"open_conversation_{conversation.conversation_id}",
            type="primary" if conversation.conversation_id == current_id else "secondary",
            use_container_width=True,
            help=f"工作区：{conversation.session_id}",
        ):
            return conversation.conversation_id

    if archived:
        expander = getattr(st, "expander", None)
        archived_section = (
            expander(f"已归档 · {len(archived)}", expanded=bool(query))
            if expander is not None
            else nullcontext()
        )
        with archived_section:
            for conversation in archived:
                if st.button(
                    conversation.title,
                    key=f"open_conversation_{conversation.conversation_id}",
                    type="primary" if conversation.conversation_id == current_id else "secondary",
                    use_container_width=True,
                    help=f"已归档 · 工作区：{conversation.session_id}",
                ):
                    return conversation.conversation_id

    selected = store.get_by_id(current_id) if current_id else None
    if selected is None:
        selected = next((item for item in conversations if item.status == "active"), None)
        if selected is None and conversations:
            selected = conversations[0]
    if selected is None:
        return None

    expander = getattr(st, "expander", None)
    management = expander("会话管理", expanded=False) if expander is not None else nullcontext()
    with management:
        st.caption(f"{selected.title} · 工作区 {selected.session_id}")
        if selected.status == "archived":
            st.caption("此会话已归档，仅可查看历史消息。")
            if st.button("取消归档", key=f"unarchive_conversation_{selected.conversation_id}"):
                store.unarchive(selected.session_id, selected.conversation_id)
                logger.info("conversation.unarchive.requested | 用户请求取消归档 | 会话ID=%s", selected.conversation_id)
                st.rerun()
        else:
            renamed = st.text_input(
                "会话名称",
                value=selected.title,
                key=f"conversation_title_{selected.conversation_id}",
            ).strip()
            if renamed and renamed != selected.title and st.button(
                "保存名称", key=f"save_conversation_title_{selected.conversation_id}"
            ):
                store.update_title(selected.session_id, selected.conversation_id, renamed)
                logger.info("conversation.rename.requested | 用户请求重命名会话 | 会话ID=%s | 状态=active | 新标题长度=%d", selected.conversation_id, len(renamed))
                st.rerun()
                return selected.conversation_id
            if st.button("归档当前会话", key=f"archive_conversation_{selected.conversation_id}"):
                store.archive(selected.session_id, selected.conversation_id)
                logger.info("conversation.archive.requested | 用户请求归档会话 | 会话ID=%s", selected.conversation_id)
                rerun = getattr(st, "rerun", None)
                if rerun is not None:
                    rerun()
                return selected.conversation_id
        if st.button("删除当前会话", key=f"delete_conversation_{selected.conversation_id}"):
            store.soft_delete(selected.session_id, selected.conversation_id)
            logger.info("conversation.delete.requested | 用户请求删除会话 | 会话ID=%s", selected.conversation_id)
            remaining = store.list_active(selected.session_id)
            if remaining:
                return remaining[0].conversation_id
            return create_new_conversation(store, session_id).conversation_id

    return selected.conversation_id
