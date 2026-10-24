from dataclasses import dataclass

from agent.events import UIEvent
from agent.state import InMemorySaver
from ui.session import AnalysisSession, create_analysis_session


def test_followup_prompt_keeps_current_analysis_context():
    from ui.followup import build_followup_prompt

    session = AnalysisSession(
        session_id="session-a", dataset_id="ds-a", analysis_id="analysis-a", thread_id="thread-a"
    )
    prompt = build_followup_prompt(session, "为什么毛利不可用？")

    assert "dataset_id=ds-a" in prompt
    assert "analysis_id=analysis-a" in prompt
    assert "为什么毛利不可用？" in prompt


def test_stream_followup_uses_session_thread_and_preserves_ui_events(monkeypatch):
    from ui.followup import stream_followup

    calls = {}
    expected = [UIEvent("text_delta", None, None, {"delta": "已完成", "done": True})]

    def fake_stream(runtime, messages, session_id, thread_id):
        calls.update(session_id=session_id, thread_id=thread_id, messages=messages)
        yield from expected

    monkeypatch.setattr("ui.followup.stream_agent", fake_stream)
    session = AnalysisSession(session_id="session-a", dataset_id="ds-a", analysis_id="analysis-a", thread_id="thread-a")
    events = list(stream_followup(object(), session, "请解释结果"))

    assert events == expected
    assert calls["session_id"] == "session-a"
    assert calls["thread_id"] == "thread-a"
    assert "ds-a" in calls["messages"][0].content


def test_reset_followup_thread_keeps_data_references():
    from ui.followup import reset_followup_thread

    from agent.agent_setup import AgentRuntime
    runtime = AgentRuntime(model=None, tools=[])
    runtime._fallback_messages[("session-a", "thread-old")] = []
    runtime._fallback_messages[("session-b", "thread-old")] = []
    session = AnalysisSession(session_id="session-a", dataset_id="ds-a", analysis_id="analysis-a", thread_id="thread-old")
    reset = reset_followup_thread(runtime, session)

    assert reset.session_id == "session-a"
    assert reset.dataset_id == "ds-a"
    assert reset.analysis_id == "analysis-a"
    assert reset.thread_id != "thread-old"
    assert ("session-a", "thread-old") not in runtime._fallback_messages
    assert ("session-b", "thread-old") in runtime._fallback_messages


def test_clear_analysis_data_is_explicit_and_session_scoped(tmp_path):
    from ui.followup import clear_analysis_data
    from storage.analyses import AnalysisStore
    from storage.artifacts import ArtifactStore

    analysis_store = AnalysisStore(tmp_path / "analyses")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    analysis_store.save("session-a", "analysis-a", {"analysis_id": "analysis-a"})
    artifact_store.register("session-a", "artifact-a", {"storage_key": "x"})
    analysis_store.save("session-b", "analysis-b", {"analysis_id": "analysis-b"})

    session = AnalysisSession(session_id="session-a", analysis_id="analysis-a", report_ids=["artifact-a"])
    clear_analysis_data(session, analysis_store=analysis_store, artifact_store=artifact_store)

    assert not (tmp_path / "analyses" / "session-a" / "analysis-a.json").exists()
    assert not (tmp_path / "artifacts" / "session-a" / "artifact-a.json").exists()
    assert (tmp_path / "analyses" / "session-b" / "analysis-b.json").exists()
from agent.events import UIEvent


def test_collect_followup_response_accumulates_text_and_keeps_tool_events():
    from ui.followup import collect_followup_response

    events = [
        UIEvent("tool_started", "call-a", "inspect_dataset", {"args": {}}),
        UIEvent("text_delta", None, None, {"delta": "毛利", "done": False}),
        UIEvent("tool_finished", "call-a", "inspect_dataset", {"content": "ok"}),
        UIEvent("text_delta", None, None, {"delta": "不可用。", "done": True}),
    ]

    response = collect_followup_response(events)

    assert response.text == "毛利不可用。"
    assert response.events == events


def test_graph_stream_binds_identity_and_yields_before_consuming_all_events():
    from agent.agent_setup import AgentRuntime, stream_agent
    from agent.context import require_runtime_context, get_runtime_context
    from langchain_core.messages import AIMessageChunk

    consumed = []
    class Graph:
        def stream(self, payload, config, stream_mode):
            assert require_runtime_context().session_id == "session-a"
            assert require_runtime_context().thread_id == "thread-a"
            consumed.append("first")
            yield (AIMessageChunk(content="销售"), {})
            consumed.append("second")
            yield (AIMessageChunk(content="上升"), {})

    runtime = AgentRuntime(model=None, tools=[], graph=Graph())
    stream = stream_agent(runtime, [], "session-a", "thread-a")
    assert next(stream).payload["delta"] == "销售"
    assert consumed == ["first"]
    assert next(stream).payload["delta"] == "上升"
    stream.close()
    assert get_runtime_context() is None


def test_reset_ui_conversation_keeps_result_and_dataset(monkeypatch):
    from ui.followup import reset_followup_ui
    state = {"analysis_session": AnalysisSession(session_id="s", dataset_id="ds", analysis_id="a"),
             "analysis_result": object(), "followup_messages": [1], "followup_events": [2]}
    result = state["analysis_result"]
    reset_followup_ui(state)
    assert state["analysis_session"].dataset_id == "ds"
    assert state["analysis_session"].analysis_id == "a"
    assert state["analysis_result"] is result
    assert state["followup_messages"] == []
    assert state["followup_events"] == []
