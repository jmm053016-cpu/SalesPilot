from pathlib import Path

import pytest

from models.conversation import Conversation
from storage.conversations import ConversationStore


def test_archive_removes_active_visibility_but_keeps_history_readable(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a", title="待归档")
    store.append_message("session-a", conversation.conversation_id, role="user", content="历史问题")

    archived = store.archive("session-a", conversation.conversation_id)

    assert archived.status == "archived"
    assert store.list_active("session-a") == []
    restored = store.get("session-a", conversation.conversation_id)
    assert restored is not None
    assert restored.status == "archived"
    assert [m.content for m in store.list_messages("session-a", conversation.conversation_id)] == ["历史问题"]


def test_archived_conversation_can_be_unarchived_and_continued(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a")
    store.append_message("session-a", conversation.conversation_id, role="user", content="原问题")
    store.archive("session-a", conversation.conversation_id)

    restored = store.unarchive("session-a", conversation.conversation_id)

    assert restored.status == "active"
    assert store.list_active("session-a")[0].conversation_id == conversation.conversation_id
    assert store.append_message(
        "session-a", conversation.conversation_id, role="user", content="继续追问"
    ).content == "继续追问"


def test_unarchive_rejects_active_conversation(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a")

    with pytest.raises(PermissionError, match="archived"):
        store.unarchive("session-a", conversation.conversation_id)


def test_archived_conversation_is_read_only_and_cannot_append(tmp_path: Path) -> None:
    from ui.conversations import switch_conversation

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a")
    store.archive("session-a", conversation.conversation_id)

    with pytest.raises(PermissionError, match="active"):
        store.append_message("session-a", conversation.conversation_id, role="user", content="不能继续")
    assert switch_conversation(store, "session-a", conversation.conversation_id).conversation_id == conversation.conversation_id


def test_deleted_conversation_is_not_readable_or_switchable(tmp_path: Path) -> None:
    from ui.conversations import switch_conversation

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a")
    store.append_message("session-a", conversation.conversation_id, role="user", content="待删除")
    store.soft_delete("session-a", conversation.conversation_id)

    assert store.get("session-a", conversation.conversation_id) is None
    with pytest.raises(LookupError):
        switch_conversation(store, "session-a", conversation.conversation_id)


def test_soft_delete_can_remove_archived_conversation(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session-a")
    store.archive("session-a", conversation.conversation_id)

    store.soft_delete("session-a", conversation.conversation_id)

    assert store.get("session-a", conversation.conversation_id) is None


def test_can_continue_requires_active_conversation_and_existing_dataset() -> None:
    from ui.conversations import can_continue

    conversation = Conversation(
        conversation_id="c1", session_id="s1", title="会话", thread_id="t1", dataset_id="ds1"
    )
    assert can_continue(conversation, dataset_exists=True)
    assert not can_continue(conversation, dataset_exists=False)
    assert not can_continue(
        Conversation(
            conversation_id="c2", session_id="s1", title="归档", thread_id="t2",
            dataset_id="ds1", status="archived",
        ),
        dataset_exists=True,
    )
    assert not can_continue(
        Conversation(
            conversation_id="c3", session_id="s1", title="无数据", thread_id="t3"
        ),
        dataset_exists=True,
    )


def test_soft_delete_does_not_touch_external_resource_files(tmp_path: Path) -> None:
    from storage.analyses import AnalysisStore
    from storage.artifacts import ArtifactStore

    conversation_store = ConversationStore(tmp_path / "conversations.sqlite3")
    analysis_store = AnalysisStore(tmp_path / "analyses")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    conversation = conversation_store.create("session-a")
    analysis_store.save("session-a", "analysis-1", {"value": 1})
    artifact_store.register("session-a", "report-1", {"value": 2})

    conversation_store.soft_delete("session-a", conversation.conversation_id)

    assert analysis_store.get("session-a", "analysis-1") == {"value": 1}
    assert artifact_store.resolve("session-a", "report-1") == {"value": 2}
