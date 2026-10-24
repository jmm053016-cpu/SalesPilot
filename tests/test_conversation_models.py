from dataclasses import FrozenInstanceError

import pytest

from models.conversation import Conversation, ConversationMessage


def test_conversation_has_safe_defaults_and_is_immutable() -> None:
    conversation = Conversation(
        conversation_id="conv_1",
        session_id="session_1",
        title="新建会话",
        thread_id="thread_1",
        created_at="2026-10-16T10:00:00+08:00",
        updated_at="2026-10-16T10:00:00+08:00",
    )

    assert conversation.status == "active"
    assert conversation.dataset_id is None
    assert conversation.analysis_id is None
    assert conversation.report_ids == []
    with pytest.raises(FrozenInstanceError):
        conversation.title = "changed"


def test_conversation_rejects_empty_identity_and_invalid_status() -> None:
    with pytest.raises(ValueError, match="conversation_id"):
        Conversation(
            conversation_id="",
            session_id="session_1",
            title="x",
            thread_id="thread_1",
            created_at="now",
            updated_at="now",
        )

    with pytest.raises(ValueError, match="session_id"):
        Conversation(
            conversation_id="conv_1",
            session_id="",
            title="x",
            thread_id="thread_1",
            created_at="now",
            updated_at="now",
        )

    with pytest.raises(ValueError, match="status"):
        Conversation(
            conversation_id="conv_1",
            session_id="session_1",
            title="x",
            thread_id="thread_1",
            status="unknown",
            created_at="now",
            updated_at="now",
        )


def test_message_requires_supported_role_and_non_empty_content() -> None:
    message = ConversationMessage(
        message_id="msg_1",
        conversation_id="conv_1",
        role="user",
        content="问题",
        sequence_no=1,
        created_at="2026-10-16T10:00:00+08:00",
    )
    assert message.metadata == {}

    with pytest.raises(ValueError, match="role"):
        ConversationMessage(
            message_id="msg_2",
            conversation_id="conv_1",
            role="tool",
            content="结果",
            sequence_no=2,
            created_at="now",
        )

    with pytest.raises(ValueError, match="content"):
        ConversationMessage(
            message_id="msg_3",
            conversation_id="conv_1",
            role="assistant",
            content=" ",
            sequence_no=3,
            created_at="now",
        )
