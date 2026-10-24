from dataclasses import replace

from models.conversation import Conversation
from ui.session import (
    AnalysisSession,
    create_analysis_session,
    new_conversation_session,
    session_from_conversation,
    session_to_resource_binding,
)


def test_analysis_session_can_reference_conversation() -> None:
    session = create_analysis_session("session_a", conversation_id="conv_1")

    assert session.session_id == "session_a"
    assert session.conversation_id == "conv_1"
    assert session.dataset_id is None
    assert session.thread_id


def test_new_conversation_session_starts_with_empty_analysis_state() -> None:
    conversation = Conversation(
        conversation_id="conv_1",
        session_id="session_a",
        title="新会话",
        thread_id="thread_1",
        created_at="2026-10-16T10:00:00+08:00",
        updated_at="2026-10-16T10:00:00+08:00",
    )

    session = new_conversation_session("session_a", conversation)

    assert session.conversation_id == "conv_1"
    assert session.thread_id == "thread_1"
    assert session.dataset_id is None
    assert session.analysis_id is None
    assert session.report_ids == []


def test_session_from_conversation_restores_bound_resources() -> None:
    conversation = Conversation(
        conversation_id="conv_1",
        session_id="session_a",
        title="销售分析",
        thread_id="thread_1",
        dataset_id="ds_1",
        analysis_id="analysis_1",
        report_ids=["report_1"],
        created_at="2026-10-16T10:00:00+08:00",
        updated_at="2026-10-16T10:00:00+08:00",
    )

    session = session_from_conversation(conversation)

    assert session == AnalysisSession(
        session_id="session_a",
        conversation_id="conv_1",
        dataset_id="ds_1",
        analysis_id="analysis_1",
        report_ids=["report_1"],
        thread_id="thread_1",
    )
    assert session_to_resource_binding(session) == {
        "dataset_id": "ds_1",
        "analysis_id": "analysis_1",
        "report_ids": ["report_1"],
        "thread_id": "thread_1",
    }


def test_reset_thread_keeps_conversation_and_analysis_resources() -> None:
    session = AnalysisSession(
        session_id="session_a",
        conversation_id="conv_1",
        dataset_id="ds_1",
        analysis_id="analysis_1",
        report_ids=["report_1"],
        thread_id="thread_old",
    )

    reset = replace(session, thread_id="thread_new")

    assert reset.conversation_id == "conv_1"
    assert reset.dataset_id == "ds_1"
    assert reset.analysis_id == "analysis_1"
    assert reset.report_ids == ["report_1"]
    assert reset.thread_id == "thread_new"
