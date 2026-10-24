from pathlib import Path

import pytest

from storage.conversations import ConversationStore


def test_default_store_path_is_anchored_to_project_directory() -> None:
    store = ConversationStore()

    assert store.db_path == (Path(__file__).resolve().parents[1] / ".runtime" / "conversations.sqlite3")


@pytest.mark.parametrize(
    ("module_name", "store_name", "expected_suffix"),
    [
        ("storage.datasets", "DatasetStore", Path(".runtime")),
        ("storage.analyses", "AnalysisStore", Path(".runtime/analyses")),
        ("storage.artifacts", "ArtifactStore", Path(".runtime/artifacts")),
        ("storage.uploads", "UploadStore", Path(".runtime/uploads")),
    ],
)
def test_default_file_stores_ignore_process_working_directory(
    tmp_path: Path, monkeypatch, module_name: str, store_name: str, expected_suffix: Path
) -> None:
    import importlib

    monkeypatch.chdir(tmp_path)
    module = importlib.import_module(module_name)
    store = getattr(module, store_name)()

    assert store.root == Path(__file__).resolve().parents[1] / expected_suffix


def test_reopened_store_restores_conversation_and_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "conversations.sqlite3"
    store = ConversationStore(db_path)
    conversation = store.create("session_restart", title="重启后仍存在")
    store.append_message(
        "session_restart", conversation.conversation_id, role="user", content="历史问题"
    )

    reopened = ConversationStore(db_path)

    assert reopened.get("session_restart", conversation.conversation_id).title == "重启后仍存在"
    assert [m.content for m in reopened.list_messages("session_restart", conversation.conversation_id)] == ["历史问题"]


def test_store_creates_conversation_and_persists_resources(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3")

    conversation = store.create("session_a")
    assert conversation.title == "新建会话"
    assert store.get("session_a", conversation.conversation_id) == conversation

    updated = store.bind_resources(
        "session_a",
        conversation.conversation_id,
        dataset_id="ds_1",
        analysis_id="analysis_1",
        report_ids=["report_1"],
        thread_id="thread_2",
    )
    assert updated.dataset_id == "ds_1"
    assert updated.analysis_id == "analysis_1"
    assert updated.report_ids == ["report_1"]
    assert updated.thread_id == "thread_2"


def test_store_appends_ordered_messages_and_metadata(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session_a")

    first = store.append_message(
        "session_a",
        conversation.conversation_id,
        role="user",
        content="请分析销售额",
    )
    second = store.append_message(
        "session_a",
        conversation.conversation_id,
        role="assistant",
        content="分析结果如下",
        metadata={"analysis_id": "analysis_1"},
    )

    assert first.sequence_no == 1
    assert second.sequence_no == 2
    assert store.list_messages("session_a", conversation.conversation_id) == [first, second]
    assert second.metadata == {"analysis_id": "analysis_1"}


def test_store_lists_active_conversations_by_updated_time_and_updates_title(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    older = store.create("session_a", title="旧会话")
    newer = store.create("session_a", title="新会话")

    renamed = store.update_title("session_a", older.conversation_id, "已重命名")
    conversations = store.list_active("session_a")

    assert renamed.title == "已重命名"
    assert conversations[0].conversation_id == older.conversation_id
    assert conversations[1].conversation_id == newer.conversation_id


def test_store_isolates_conversations_by_session_id(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session_a")

    assert store.get("session_b", conversation.conversation_id) is None
    with pytest.raises(PermissionError):
        store.append_message(
            "session_b",
            conversation.conversation_id,
            role="user",
            content="越权访问",
        )
    with pytest.raises(PermissionError):
        store.update_title("session_b", conversation.conversation_id, "越权修改")
    with pytest.raises(PermissionError):
        store.soft_delete("session_b", conversation.conversation_id)


def test_store_soft_deletes_conversation_and_its_messages(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session_a")
    store.append_message(
        "session_a", conversation.conversation_id, role="user", content="保留前的消息"
    )

    store.soft_delete("session_a", conversation.conversation_id)

    assert store.list_active("session_a") == []
    assert store.get("session_a", conversation.conversation_id) is None
    with pytest.raises(PermissionError):
        store.list_messages("session_a", conversation.conversation_id)


def test_store_logs_lifecycle_events_without_message_content(tmp_path: Path, caplog) -> None:
    import logging

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    logger = logging.getLogger("salespilot.storage.conversations")
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.INFO)
    try:
        conversation = store.create("session_a", title="敏感标题不应写入日志")
        store.update_title("session_a", conversation.conversation_id, "新标题")
        store.append_message("session_a", conversation.conversation_id, role="user", content="机密正文")
        store.archive("session_a", conversation.conversation_id)
        store.soft_delete("session_a", conversation.conversation_id)
    finally:
        logger.removeHandler(caplog.handler)

    messages = " ".join(record.getMessage() for record in caplog.records)
    for event in ("conversation.created", "conversation.renamed", "conversation.message.appended", "conversation.archived", "conversation.deleted"):
        assert event in messages
    assert "机密正文" not in messages
    assert "敏感标题不应写入日志" not in messages
