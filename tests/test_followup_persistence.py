from agent.events import UIEvent
from langchain_core.messages import AIMessage, HumanMessage
from storage.conversations import ConversationStore
from ui.followup import stream_followup
from ui.session import AnalysisSession


def _session(store: ConversationStore) -> AnalysisSession:
    conversation = store.create("session-a")
    return AnalysisSession(
        session_id="session-a",
        conversation_id=conversation.conversation_id,
        dataset_id="dataset-a",
        analysis_id="analysis-a",
        thread_id=conversation.thread_id,
    )


def test_stream_followup_persists_user_and_final_assistant_only(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    session = _session(store)

    def fake_stream(runtime, messages, session_id, thread_id):
        yield UIEvent("text_delta", None, None, {"delta": "你好", "done": False})
        yield UIEvent("tool_started", "call-1", "inspect_dataset", {})
        yield UIEvent("text_delta", None, None, {"delta": "，结果如下", "done": True})

    monkeypatch.setattr("ui.followup.stream_agent", fake_stream)

    events = list(stream_followup(object(), session, "请解释结果", conversation_store=store))

    messages = store.list_messages("session-a", session.conversation_id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert [message.content for message in messages] == ["请解释结果", "你好，结果如下"]
    assert len(events) == 3


def test_stream_followup_replays_persisted_history_before_current_question(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    session = _session(store)
    store.append_message("session-a", session.conversation_id, role="user", content="之前问了什么？")
    store.append_message("session-a", session.conversation_id, role="assistant", content="你之前问了销售趋势。")
    store.append_message("session-a", session.conversation_id, role="error", content="上次调用失败")
    captured = {}

    def fake_stream(runtime, messages, session_id, thread_id):
        captured["messages"] = messages
        yield UIEvent("text_delta", None, None, {"delta": "继续分析", "done": True})

    monkeypatch.setattr("ui.followup.stream_agent", fake_stream)

    list(stream_followup(object(), session, "那原因是什么？", conversation_store=store))

    messages = captured["messages"]
    assert [type(message) for message in messages] == [HumanMessage, AIMessage, HumanMessage]
    assert messages[0].content == "之前问了什么？"
    assert messages[1].content == "你之前问了销售趋势。"
    assert "dataset_id=dataset-a" in messages[-1].content
    assert "analysis_id=analysis-a" in messages[-1].content
    assert "那原因是什么？" in messages[-1].content


def test_stream_followup_persists_user_and_error_when_stream_fails(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    session = _session(store)

    def failing_stream(runtime, messages, session_id, thread_id):
        yield UIEvent("text_delta", None, None, {"delta": "部分结果", "done": False})
        raise RuntimeError("agent unavailable")

    monkeypatch.setattr("ui.followup.stream_agent", failing_stream)

    try:
        list(stream_followup(object(), session, "为什么失败？", conversation_store=store))
    except RuntimeError as exc:
        assert str(exc) == "agent unavailable"
    else:
        raise AssertionError("stream_followup should propagate stream errors")

    messages = store.list_messages("session-a", session.conversation_id)
    assert [message.role for message in messages] == ["user", "error"]
    assert messages[0].content == "为什么失败？"
    assert "agent unavailable" in messages[1].content
    assert messages[1].metadata["stage"] == "stream"


def test_stream_followup_does_not_persist_empty_assistant(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    session = _session(store)

    monkeypatch.setattr(
        "ui.followup.stream_agent",
        lambda *args: iter([UIEvent("tool_started", "call-1", "inspect_dataset", {})]),
    )

    list(stream_followup(object(), session, "只调用工具", conversation_store=store))

    messages = store.list_messages("session-a", session.conversation_id)
    assert [message.role for message in messages] == ["user"]
