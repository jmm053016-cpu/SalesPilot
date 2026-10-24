from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent import agent_setup
from agent.agent_setup import (
    AgentRuntimeError,
    create_agent_runtime,
    invoke_agent,
    new_thread_id,
    reset_agent_thread,
    stream_agent,
)
from agent.context import require_runtime_context, runtime_context
from agent.middleware import call_with_timeout




def test_create_llm_uses_deepseek_when_openai_credentials_are_missing(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(agent_setup, "ChatOpenAI", FakeChatOpenAI)

    agent_setup.create_llm()

    assert captured["model"] == "deepseek-flash"
    assert captured["api_key"] == "deepseek-test-key"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["streaming"] is True


def test_create_llm_uses_deepseek_even_when_openai_configuration_is_present(monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.example/v1")
    monkeypatch.setenv("MODEL_NAME", "gpt-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setattr(agent_setup, "ChatOpenAI", FakeChatOpenAI)

    agent_setup.create_llm()

    assert captured["model"] == "deepseek-flash"
    assert captured["api_key"] == "deepseek-test-key"
    assert captured["base_url"] == "https://api.deepseek.com"

@dataclass
@dataclass
class FakeChatModel:
    """最小假模型：记录输入，并按预设响应返回消息。"""

    responses: list[Any]
    calls: list[Any] | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def invoke(self, messages: list[Any], **kwargs: Any) -> Any:
        self.calls.append(messages)
        if not self.responses:
            return AIMessage(content="done")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeTool:
    name = "fake_tool"

    def __init__(self, result: Any = "ok", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def invoke(self, payload: dict[str, Any], **kwargs: Any) -> Any:
        self.calls.append(payload)
        if self.error:
            raise self.error
        return self.result


def _text(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("output") or result.get("text") or result.get("content"))
    return str(getattr(result, "output", None) or getattr(result, "text", None) or result)


def test_create_agent_runtime_accepts_fake_model_and_tools() -> None:
    model = FakeChatModel([AIMessage(content="ready")])
    tool = FakeTool()

    runtime = create_agent_runtime(model=model, tools=[tool])
    result = invoke_agent(runtime, [HumanMessage(content="hello")], session_id="session-a")

    assert "ready" in _text(result)
    assert model.calls
    assert any(message.content == "hello" for message in model.calls[0])


def test_timeout_worker_inherits_agent_runtime_context() -> None:
    with runtime_context("session-context", "thread-context"):
        context = call_with_timeout(require_runtime_context, 1)

    assert context.session_id == "session-context"
    assert context.thread_id == "thread-context"


def test_fallback_stream_emits_finished_tool_result_for_resource_binding():
    model = FakeChatModel([
        AIMessage(
            content="",
            tool_calls=[{"id": "call-1", "name": "fake_tool", "args": {}}],
        ),
        AIMessage(content="analysis complete"),
    ])
    runtime = create_agent_runtime(model=model, tools=[FakeTool({"ok": True, "dataset_id": "ds_stream"})])

    events = list(stream_agent(runtime, [HumanMessage(content="analyze")], "session-stream", "thread-stream"))

    assert any(event.type == "tool_started" and event.name == "fake_tool" for event in events)
    finished = next(event for event in events if event.type == "tool_finished")
    assert finished.call_id == "call-1"
    assert "ds_stream" in finished.payload["content"]


def test_graph_stream_recovers_tool_results_missing_from_stream_updates():
    from types import SimpleNamespace
    from langchain_core.messages import ToolMessage

    user_message = HumanMessage(content="analyze current upload")

    class GraphWithIncompleteStream:
        def stream(self, *_args, **_kwargs):
            yield ("updates", {"model": {"messages": [AIMessage(content="starting analysis")]}})

        def get_state(self, _config):
            return SimpleNamespace(values={"messages": [
                user_message,
                AIMessage(content="", tool_calls=[{
                    "id": "call-recovered", "name": "validate_and_save_dataset", "args": {}
                }]),
                ToolMessage(
                    content='{"ok":true,"status":"dataset_saved","dataset_id":"ds_recovered"}',
                    tool_call_id="call-recovered",
                    name="validate_and_save_dataset",
                ),
            ]})

    runtime = create_agent_runtime(model=FakeChatModel([]), tools=[])
    runtime.graph = GraphWithIncompleteStream()

    events = list(stream_agent(runtime, [user_message], "session-recovery", "thread-recovery"))

    finished = [event for event in events if event.type == "tool_finished"]
    assert len(finished) == 1
    assert finished[0].call_id == "call-recovered"
    assert "ds_recovered" in finished[0].payload["content"]


def test_graph_stream_hides_intermediate_model_text_before_tool_calls():
    from langchain_core.messages import AIMessageChunk, ToolMessage

    class GraphWithIntermediateText:
        def stream(self, *_args, **_kwargs):
            yield (AIMessageChunk(content="{'ok': True, 'metrics': {…}}"), {"langgraph_node": "model"})
            yield ("updates", {"model": {"messages": [AIMessage(content="", tool_calls=[{
                "id": "call-analysis", "name": "run_sales_analysis", "args": {}
            }])]}})
            yield ("updates", {"tools": {"messages": [ToolMessage(
                content='{"ok":true,"analysis_id":"a1"}', tool_call_id="call-analysis"
            )]}})
            yield (AIMessageChunk(content="净销售额为 1,980 USD。"), {"langgraph_node": "model"})

    runtime = create_agent_runtime(model=FakeChatModel([]), tools=[])
    runtime.graph = GraphWithIntermediateText()

    events = list(stream_agent(runtime, [HumanMessage(content="分析销售额")], "s", "t"))

    visible_text = "".join(
        event.payload.get("delta", "") for event in events if event.type == "text_delta"
    )
    assert visible_text == "净销售额为 1,980 USD。"


def test_stream_logs_tool_lifecycle_without_logging_arguments(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    model = FakeChatModel([
        AIMessage(content="", tool_calls=[{
            "id": "call-lifecycle", "name": "fake_tool",
            "args": {"private_value": "do-not-log"},
        }]),
        AIMessage(content="done"),
    ])
    runtime = create_agent_runtime(model=model, tools=[FakeTool()])

    with caplog.at_level(logging.INFO, logger="salespilot.agent.agent_setup"):
        list(stream_agent(runtime, [HumanMessage(content="analyze")], "session-log", "thread-lifecycle"))

    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "agent.tool.started" in output
    assert "agent.tool.finished" in output
    assert "fake_tool" in output
    assert "call-lifecycle" in output
    assert "private_value" not in output
    assert "do-not-log" not in output


def test_new_thread_id_is_unique_and_reset_does_not_inherit_old_messages() -> None:
    model = FakeChatModel([AIMessage(content="first"), AIMessage(content="second")])
    runtime = create_agent_runtime(model=model, tools=[])
    old_thread = new_thread_id()
    new_thread = new_thread_id()

    first = invoke_agent(
        runtime,
        [HumanMessage(content="private old message")],
        session_id="session-a",
        thread_id=old_thread,
    )
    reset_agent_thread(runtime, old_thread)
    second = invoke_agent(
        runtime,
        [HumanMessage(content="new conversation")],
        session_id="session-a",
        thread_id=new_thread,
    )

    assert old_thread != new_thread
    assert "first" in _text(first)
    assert "second" in _text(second)
    assert not any(
        getattr(message, "content", "") == "private old message"
        for message in model.calls[-1]
    )


def test_thread_state_isolated_between_sessions() -> None:
    model = FakeChatModel([AIMessage(content="a"), AIMessage(content="b")])
    runtime = create_agent_runtime(model=model, tools=[])
    thread = new_thread_id()

    invoke_agent(runtime, [HumanMessage(content="session a secret")], "session-a", thread_id=thread)
    invoke_agent(runtime, [HumanMessage(content="session b input")], "session-b", thread_id=thread)

    assert not any(
        getattr(message, "content", "") == "session a secret"
        for message in model.calls[-1]
    )


def test_fallback_persists_history_through_injected_checkpointer() -> None:
    class RecordingSaver:
        def __init__(self) -> None:
            self.states: dict[tuple[str, str], dict[str, Any]] = {}

        def get(self, *, session_id: str, thread_id: str) -> dict[str, Any] | None:
            return self.states.get((session_id, thread_id))

        def put(self, *, session_id: str, thread_id: str, state: dict[str, Any]) -> None:
            self.states[(session_id, thread_id)] = state

    saver = RecordingSaver()
    model = FakeChatModel([AIMessage(content="first"), AIMessage(content="second")])
    runtime = create_agent_runtime(model=model, tools=[], checkpointer=saver)
    thread_id = "thread-a"

    invoke_agent(runtime, [HumanMessage(content="remember this")], "session-a", thread_id)
    invoke_agent(runtime, [HumanMessage(content="follow up")], "session-a", thread_id)

    assert ("session-a", thread_id) in saver.states
    assert any(message.content == "remember this" for message in model.calls[-1])


def test_fallback_uses_native_langgraph_checkpointer() -> None:
    from langgraph.checkpoint.memory import InMemorySaver as GraphInMemorySaver

    saver = GraphInMemorySaver()
    model = FakeChatModel([AIMessage(content="first"), AIMessage(content="second")])
    runtime = create_agent_runtime(model=model, tools=[], checkpointer=saver)

    invoke_agent(runtime, [HumanMessage(content="remember this")], "session-a", "thread-a")
    invoke_agent(runtime, [HumanMessage(content="follow up")], "session-a", "thread-a")

    checkpoint = saver.get_tuple({"configurable": {
        "thread_id": '["session-a","thread-a"]', "checkpoint_ns": ""
    }})
    assert checkpoint is not None
    assert any(message.content == "remember this" for message in model.calls[-1])


def test_reset_deletes_native_langgraph_checkpoint() -> None:
    from langgraph.checkpoint.memory import InMemorySaver as GraphInMemorySaver

    saver = GraphInMemorySaver()
    model = FakeChatModel([AIMessage(content="first")])
    runtime = create_agent_runtime(model=model, tools=[], checkpointer=saver)
    invoke_agent(runtime, [HumanMessage(content="forget this")], "session-a", "thread-a")

    reset_agent_thread(runtime, "thread-a", "session-a")

    checkpoint = saver.get_tuple({"configurable": {
        "thread_id": '["session-a","thread-a"]', "checkpoint_ns": ""
    }})
    assert checkpoint is None


def test_default_saver_supports_both_runtime_contracts() -> None:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    runtime = create_agent_runtime(model=FakeChatModel([]), tools=[])
    assert isinstance(runtime.checkpointer, BaseCheckpointSaver)
    runtime.checkpointer.put(session_id="session-a", thread_id="thread-a",
                             state={"messages": [HumanMessage(content="saved")]})
    state = runtime.checkpointer.get(session_id="session-a", thread_id="thread-a")
    assert state["messages"][0].content == "saved"


def test_graph_checkpoint_thread_key_is_session_scoped() -> None:
    captured: list[str] = []

    class Graph:
        def invoke(self, payload: Any, config: dict[str, Any]) -> dict[str, Any]:
            captured.append(config["configurable"]["thread_id"])
            return {}

    runtime = create_agent_runtime(model=FakeChatModel([]), tools=[])
    runtime.graph = Graph()
    invoke_agent(runtime, [], "session-a", "same-thread")
    invoke_agent(runtime, [], "session-b", "same-thread")
    assert captured[0] != captured[1]

def test_graph_receives_the_runtime_checkpointer(monkeypatch: pytest.MonkeyPatch) -> None:
    import langchain.agents

    captured: dict[str, Any] = {}

    class GraphModel(FakeChatModel):
        def bind_tools(self, tools: list[Any]) -> "GraphModel":
            return self

    from langgraph.checkpoint.memory import InMemorySaver as GraphInMemorySaver

    def fake_create_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(langchain.agents, "create_agent", fake_create_agent)
    saver = GraphInMemorySaver()
    runtime = create_agent_runtime(model=GraphModel([]), tools=[], checkpointer=saver)

    assert runtime.graph is not None
    assert captured["checkpointer"] is saver
def test_graph_runtime_guards_apply_timeout_and_tool_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    import time
    import langchain.agents
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver as GraphInMemorySaver

    captured: dict[str, Any] = {}

    class GraphModel(FakeChatModel):
        def bind_tools(self, tools: list[Any]) -> "GraphModel":
            return self

    def fake_create_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(langchain.agents, "create_agent", fake_create_agent)
    create_agent_runtime(model=GraphModel([]), tools=[], checkpointer=GraphInMemorySaver(),
                         timeout_seconds=0.01, max_tool_calls=0)
    guards = captured["middleware"][0]

    with pytest.raises(TimeoutError):
        guards.wrap_model_call(object(), lambda _: time.sleep(0.1))

    from langchain_core.messages import ToolMessage
    timed_out = guards.wrap_tool_call(
        SimpleNamespace(state={"messages": []}, tool_call={"id": "slow", "name": "slow_tool"}),
        lambda _: time.sleep(0.1),
    )
    assert isinstance(timed_out, ToolMessage)
    assert timed_out.status == "error"

    request = SimpleNamespace(state={"messages": [
        AIMessage(content="", tool_calls=[{"name": "tool", "args": {}, "id": "call-1"}])
    ]}, tool_call={"name": "tool", "args": {}, "id": "call-1"})
    rejected = guards.wrap_tool_call(request, lambda _: pytest.fail("over-budget tool executed"))
    assert rejected.status == "error"
    assert "tool_limit" in rejected.content

def test_tool_call_limit_is_enforced() -> None:
    model = FakeChatModel([AIMessage(content="keep going")])
    tool = FakeTool()
    runtime = create_agent_runtime(model=model, tools=[tool], max_tool_calls=1)

    with pytest.raises(AgentRuntimeError, match="tool.*limit|工具.*次数"):
        invoke_agent(runtime, [HumanMessage(content="call tools repeatedly")], "session-a")


def test_stream_logs_tool_budget_failure_without_logging_arguments(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    model = FakeChatModel([
        AIMessage(content="", tool_calls=[{
            "id": "call-over-budget", "name": "fake_tool",
            "args": {"secret_customer_data": "must-not-appear"},
        }]),
    ])
    runtime = create_agent_runtime(model=model, tools=[FakeTool()], max_tool_calls=0)

    with caplog.at_level(logging.INFO, logger="salespilot.agent.agent_setup"):
        events = list(stream_agent(runtime, [HumanMessage(content="analyze")], "session-log", "thread-log"))
    assert any(event.type == "text_delta" for event in events)

    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "fake_tool" in output
    assert "call-over-budget" in output
    assert "tool_limit" in output
    assert "secret_customer_data" not in output
    assert "must-not-appear" not in output


def test_fallback_tool_budget_counts_calls_across_turns() -> None:
    model = FakeChatModel([
        AIMessage(content="", tool_calls=[{"id": "call-1", "name": "fake_tool", "args": {}}]),
        AIMessage(content="first done"),
        AIMessage(content="", tool_calls=[{"id": "call-2", "name": "fake_tool", "args": {}}]),
    ])
    runtime = create_agent_runtime(model=model, tools=[FakeTool()], max_tool_calls=1)

    invoke_agent(runtime, [HumanMessage(content="first")], "session-a", "thread-a")
    result = invoke_agent(runtime, [HumanMessage(content="second")], "session-a", "thread-a")
    assert "done" in _text(result)

def test_fallback_tool_budget_counts_each_tool_call_once() -> None:
    model = FakeChatModel([
        AIMessage(content="", tool_calls=[{"id": "call-1", "name": "fake_tool", "args": {}}]),
        AIMessage(content="first done"),
        AIMessage(content="", tool_calls=[{"id": "call-2", "name": "fake_tool", "args": {}}]),
        AIMessage(content="second done"),
    ])
    tool = FakeTool()
    runtime = create_agent_runtime(model=model, tools=[tool], max_tool_calls=2)

    invoke_agent(runtime, [HumanMessage(content="first")], "session-a", "thread-a")
    result = invoke_agent(runtime, [HumanMessage(content="second")], "session-a", "thread-a")

    assert _text(result) == "second done"
    assert len(tool.calls) == 2


def test_default_tool_budget_allows_thirteen_calls_across_managed_steps() -> None:
    responses = []
    for index in range(13):
        responses.extend([
            AIMessage(content="", tool_calls=[{
                "id": f"call-{index}", "name": "fake_tool", "args": {},
            }]),
            AIMessage(content=f"step {index} done"),
        ])
    model = FakeChatModel(responses)
    tool = FakeTool()
    runtime = create_agent_runtime(model=model, tools=[tool])

    for index in range(13):
        result = invoke_agent(
            runtime, [HumanMessage(content=f"step {index}")], "session-budget", "thread-budget"
        )

    assert len(tool.calls) == 13
    assert _text(result) == "step 12 done"

def test_fallback_tool_timeout_is_classified() -> None:
    import time

    class SlowTool(FakeTool):
        def invoke(self, payload: dict[str, Any], **kwargs: Any) -> Any:
            time.sleep(0.05)
            return super().invoke(payload, **kwargs)

    model = FakeChatModel([
        AIMessage(content="", tool_calls=[{"id": "call-1", "name": "fake_tool", "args": {}}]),
    ])
    runtime = create_agent_runtime(model=model, tools=[SlowTool()], timeout_seconds=0.01)

    result = invoke_agent(runtime, [HumanMessage(content="run slowly")], "session-a")
    assert "done" in _text(result)

def test_model_timeout_is_classified() -> None:
    model = FakeChatModel([TimeoutError("slow model")])
    runtime = create_agent_runtime(model=model, tools=[], timeout_seconds=0.01)

    with pytest.raises(AgentRuntimeError, match="timeout|超时"):
        invoke_agent(runtime, [HumanMessage(content="wait")], "session-a")


def test_tool_errors_are_returned_to_model_for_recovery() -> None:
    from langchain_core.messages import ToolMessage

    model = FakeChatModel([
        AIMessage(content="use fake_tool"),
        AIMessage(content="recovered after tool error"),
    ])
    tool = FakeTool(error=ValueError("bad input"))
    runtime = create_agent_runtime(model=model, tools=[tool])

    result = invoke_agent(runtime, [HumanMessage(content="run it")], "session-a")

    assert "recovered" in _text(result)
    assert len(model.calls) == 2
    error_message = next(message for message in model.calls[1] if isinstance(message, ToolMessage))
    assert error_message.status == "error"
    assert "tool_error" in error_message.content


def test_duplicate_analysis_call_is_rejected_without_running_tool(monkeypatch) -> None:
    from types import SimpleNamespace
    import langchain.agents
    from langchain_core.messages import ToolMessage
    from langgraph.checkpoint.memory import InMemorySaver as GraphInMemorySaver

    captured: dict[str, Any] = {}

    class GraphModel(FakeChatModel):
        def bind_tools(self, tools: list[Any]) -> "GraphModel":
            return self

    def fake_create_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(langchain.agents, "create_agent", fake_create_agent)
    create_agent_runtime(model=GraphModel([]), tools=[], checkpointer=GraphInMemorySaver())
    guards = captured["middleware"][0]
    args = {"dataset_id": "ds-1", "request_json": "{\"current_start\":\"2024-01-01\"}"}
    request = SimpleNamespace(
        state={"messages": [
            HumanMessage(content="analyze"),
            AIMessage(content="", tool_calls=[{"id": "prior", "name": "run_sales_analysis", "args": args}]),
            ToolMessage(content="previous result", tool_call_id="prior"),
            AIMessage(content="", tool_calls=[{"id": "duplicate", "name": "run_sales_analysis", "args": args}]),
        ]},
        tool_call={"id": "duplicate", "name": "run_sales_analysis", "args": args},
    )

    result = guards.wrap_tool_call(request, lambda _: pytest.fail("duplicate analysis executed"))

    assert isinstance(result, ToolMessage)


def test_duplicate_import_call_is_rejected_without_running_tool(monkeypatch) -> None:
    from types import SimpleNamespace
    import langchain.agents
    from langchain_core.messages import ToolMessage
    from langgraph.checkpoint.memory import InMemorySaver as GraphInMemorySaver

    captured: dict[str, Any] = {}

    class GraphModel(FakeChatModel):
        def bind_tools(self, tools: list[Any]) -> "GraphModel":
            return self

    def fake_create_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(langchain.agents, "create_agent", fake_create_agent)
    create_agent_runtime(model=GraphModel([]), tools=[], checkpointer=GraphInMemorySaver())
    guards = captured["middleware"][0]
    args = {"source_id": "src-1"}
    request = SimpleNamespace(
        state={"messages": [
            HumanMessage(content="import"),
            AIMessage(content="", tool_calls=[{"id": "prior", "name": "inspect_import_source", "args": args}]),
            ToolMessage(content="previous result", tool_call_id="prior"),
        ]},
        tool_call={"id": "duplicate", "name": "inspect_import_source", "args": args},
    )

    result = guards.wrap_tool_call(request, lambda _: pytest.fail("duplicate import executed"))

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "identical inspect_import_source" in result.content
    assert result.status == "error"
    assert "identical" in result.content

def test_fallback_can_choose_another_tool_after_tool_error() -> None:
    class AlternativeTool:
        name = "alternative_tool"

        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, payload: dict[str, Any], **kwargs: Any) -> str:
            self.calls += 1
            return "alternative result"

    model = FakeChatModel([
        AIMessage(content="", tool_calls=[{"id": "failed", "name": "fake_tool", "args": {}}]),
        AIMessage(content="", tool_calls=[{"id": "alternative", "name": "alternative_tool", "args": {}}]),
        AIMessage(content="answered from alternative result"),
    ])
    alternative = AlternativeTool()
    runtime = create_agent_runtime(
        model=model,
        tools=[FakeTool(error=ValueError("first tool failed")), alternative],
        max_tool_calls=3,
    )

    result = invoke_agent(runtime, [HumanMessage(content="analyze")], "fallback-recovery")

    assert "alternative result" in _text(result)
    assert alternative.calls == 1
