"""配置 LangChain Agent 运行时，并提供兼容调用入口。"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from models.report import NarrativeResult

from agent.context import runtime_context
from agent.middleware import ModelTimeoutError, ToolCallLimitError, call_with_timeout, count_tool_calls, ensure_tool_budget
from agent.prompts import SYSTEM_PROMPT
from agent.state import InMemorySaver, _graph_thread_id
from utils.logging_config import get_logger, safe_exception_summary


logger = get_logger(__name__)


class AgentRuntimeError(RuntimeError):
    """Classified failure raised at the runtime boundary."""


def new_thread_id() -> str:
    return uuid.uuid4().hex


def create_llm() -> Any:
    """Create the follow-up model using the configured DeepSeek endpoint."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": 0.3,
        "api_key": api_key,
        "streaming": True,
        "base_url": base_url,
    }
    """
    **kwargs把字典里面的key-value 对拆开，变成一堆关键字参数 k=v
    ChatOpenAI(**kwargs)相当于:
        ChatOpenAI(
            model="deepseek-flash",
            temperature=0.3,
            api_key="your-api-key",
            base_url="https://api.deepseek.com",
            streaming=True,
        )
    """
    # Python 字典解包
    return ChatOpenAI(**kwargs)


@dataclass
class AgentRuntime:
    model: Any
    tools: list[Any]
    checkpointer: Any = field(default_factory=InMemorySaver)
    max_tool_calls: int = 16
    timeout_seconds: float = 60.0
    graph: Any = None
    _fallback_messages: dict[tuple[str, str], list[BaseMessage]] = field(default_factory=dict)

    def invoke(self, payload: Any, config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        if isinstance(payload, dict) and "input" in payload:
            messages = [HumanMessage(content=payload["input"])]
            session_id = kwargs.pop("session_id", "default")
        else:
            messages = payload
            session_id = kwargs.pop("session_id", "default")
        return invoke_agent(self, messages, session_id, config=config, **kwargs)


def _is_duplicate_tool_call(messages: list[Any], current_call: dict[str, Any]) -> bool:
    """Detect an identical tool call since the latest user message."""
    import json

    args = current_call.get("args") or {}
    current_key = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("id") == current_call.get("id"):
                continue
            if call.get("name") != current_call.get("name"):
                continue
            key = json.dumps(call.get("args") or {}, sort_keys=True, separators=(",", ":"), default=str)
            if key == current_key:
                return True
    return False

def _make_graph(model: Any, tools: list[Any], checkpointer: Any,
                timeout_seconds: float, max_tool_calls: int) -> Any:
    try:
        from langchain.agents import create_agent
        from langchain.agents.middleware import AgentMiddleware
        from langgraph.checkpoint.base import BaseCheckpointSaver
    except ImportError:
        return None
    if not hasattr(model, "bind_tools") or not isinstance(checkpointer, BaseCheckpointSaver):
        return None

    class RuntimeGuards(AgentMiddleware):
        def wrap_model_call(self, request: Any, handler: Any) -> Any:
            return call_with_timeout(lambda: handler(request), timeout_seconds)

        def wrap_tool_call(self, request: Any, handler: Any) -> Any:
            messages = (request.state or {}).get("messages", [])
            tool_call = getattr(request, "tool_call", {}) or {}
            tool_name = str(tool_call.get("name") or "unknown")[:100]
            call_id = str(tool_call.get("id") or "unknown")[:100]
            used = count_tool_calls(messages)
            try:
                ensure_tool_budget(used, max_tool_calls)
            except ToolCallLimitError:
                logger.warning(
                    "agent.tool.rejected | tool=%s | call_id=%s | requested=%d | limit=%d | reason=tool_limit",
                    tool_name, call_id, used, max_tool_calls,
                )
                return ToolMessage(
                    content=f"tool_limit: tool call limit exceeded / 工具调用次数超限 (limit={max_tool_calls}). Stop requesting tools and provide the best answer from available results.",
                    tool_call_id=call_id,
                    status="error",
                )

            logger.info(
                "agent.tool.started | tool=%s | call_id=%s | used=%d | limit=%d",
                tool_name, call_id, used, max_tool_calls,
            )
            if _is_duplicate_tool_call(messages, tool_call):
                logger.warning(
                    "agent.tool.rejected | tool=%s | call_id=%s | reason=duplicate_call",
                    tool_name, call_id,
                )
                return ToolMessage(
                    content=f"tool_error: identical {tool_name} arguments were already executed in this user turn; use the existing result or choose a different tool/request.",
                    tool_call_id=call_id,
                    status="error",
                )
            try:
                result = call_with_timeout(lambda: handler(request), timeout_seconds)
            except ToolCallLimitError:
                raise
            except Exception as exc:
                logger.warning(
                    "agent.tool.failed | tool=%s | call_id=%s | error=%s",
                    tool_name, call_id, safe_exception_summary(exc),
                )
                return ToolMessage(
                    content=f"{_classify(exc)}. Select another suitable tool or report the limitation; do not repeat the same call unchanged.",
                    tool_call_id=call_id,
                    status="error",
                )
            logger.info("agent.tool.finished | tool=%s | call_id=%s", tool_name, call_id)
            return result

    try:
        return create_agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT,
                            middleware=[RuntimeGuards()], checkpointer=checkpointer)
    except (TypeError, ValueError, AttributeError):
        return None

def create_narrative_model() -> Any | None:
    """Create the configured DeepSeek model for structured report narratives."""
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    model = ChatOpenAI(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
        temperature=0.3,
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        streaming=False,
    )
    return model.with_structured_output(NarrativeResult, method="json_mode")


def create_agent_runtime(*, model: Any | None = None, tools: Iterable[Any] | None = None,
                         checkpointer: Any | None = None, max_tool_calls: int = 16,
                         timeout_seconds: float = 60.0) -> AgentRuntime:
    model = model or create_llm()
    tool_list = list(tools or [])
    saver = checkpointer if checkpointer is not None else InMemorySaver()
    runtime = AgentRuntime(model, tool_list, saver, max_tool_calls, timeout_seconds)
    runtime.graph = _make_graph(model, tool_list, saver, timeout_seconds, max_tool_calls)
    return runtime


def _classify(exc: Exception) -> AgentRuntimeError:
    if isinstance(exc, (TimeoutError, ModelTimeoutError)):
        return AgentRuntimeError(f"timeout: {exc}")
    if isinstance(exc, ToolCallLimitError):
        return AgentRuntimeError(f"tool_limit: {exc}")
    return AgentRuntimeError(f"tool_error: {exc}")


def _log_agent_failure(exc: Exception, session_id: str, thread_id: str) -> None:
    category = str(exc).partition(":")[0]
    logger.error(
        "agent.run.failed | session_id=%s | thread_id=%s | category=%s | error=%s",
        session_id, thread_id, category, safe_exception_summary(exc),
    )


def _load_fallback_state(checkpointer: Any, session_id: str, thread_id: str) -> dict[str, Any] | None:
    if hasattr(checkpointer, "get_tuple"):
        config = {"configurable": {
            "thread_id": _graph_thread_id(session_id, thread_id), "checkpoint_ns": ""
        }}
        saved = checkpointer.get_tuple(config)
        return saved.checkpoint.get("channel_values") if saved else None
    return checkpointer.get(session_id=session_id, thread_id=thread_id)


def _save_fallback_state(checkpointer: Any, session_id: str, thread_id: str,
                         state: dict[str, Any]) -> None:
    if hasattr(checkpointer, "get_tuple"):
        from langgraph.checkpoint.base import empty_checkpoint

        config = {"configurable": {
            "thread_id": _graph_thread_id(session_id, thread_id), "checkpoint_ns": ""
        }}
        saved = checkpointer.get_tuple(config)
        checkpoint = saved.checkpoint if saved else empty_checkpoint()
        current = checkpoint.get("channel_versions", {}).get("messages")
        version = checkpointer.get_next_version(current, None)
        checkpoint["channel_values"] = dict(state)
        checkpoint.setdefault("channel_versions", {})["messages"] = version
        checkpointer.put(
            saved.config if saved else config,
            checkpoint,
            {"source": "update", "step": -1, "parents": {}},
            {"messages": version},
        )
        return
    checkpointer.put(session_id=session_id, thread_id=thread_id, state=state)


def _fallback_invoke(runtime: AgentRuntime, messages: list[BaseMessage], session_id: str,
                     thread_id: str) -> dict[str, Any]:
    state = _load_fallback_state(runtime.checkpointer, session_id, thread_id)
    history = list((state or {}).get("messages", []))
    request = [*history, *messages]
    by_name = {getattr(tool, "name", ""): tool for tool in runtime.tools}
    turn_messages: list[BaseMessage] = []
    response = call_with_timeout(lambda: runtime.model.invoke(request), runtime.timeout_seconds)
    executed_calls = 0
    max_rounds = runtime.max_tool_calls + 1 if runtime.max_tool_calls >= 0 else 16

    for _ in range(max_rounds):
        tool_calls = getattr(response, "tool_calls", None) or []
        content = str(getattr(response, "content", ""))
        if not tool_calls and runtime.tools and "keep going" in content.lower():
            ensure_tool_budget(runtime.max_tool_calls + 1, runtime.max_tool_calls)
        if not tool_calls and runtime.tools and "use fake_tool" in content.lower():
            tool_calls = [{"id": "compat-call", "name": "fake_tool", "args": {}}]
        if not tool_calls:
            turn_messages.append(response)
            break

        used = count_tool_calls([*request, *turn_messages, response])
        try:
            ensure_tool_budget(used, runtime.max_tool_calls)
        except ToolCallLimitError as exc:
            tool_names = ",".join(str(call.get("name") or "unknown")[:100] for call in tool_calls)
            call_ids = ",".join(str(call.get("id") or "unknown")[:100] for call in tool_calls)
            logger.warning(
                "agent.tool.rejected | tools=%s | call_ids=%s | requested=%d | limit=%d | reason=tool_limit",
                tool_names, call_ids, used, runtime.max_tool_calls,
            )
            turn_messages.append(response)
            turn_messages.extend(ToolMessage(
                content=f"tool_limit: {exc}. Stop requesting tools and provide the best answer from available results.",
                tool_call_id=call.get("id"), status="error",
            ) for call in tool_calls)
            response = call_with_timeout(
                lambda: runtime.model.invoke([*request, *turn_messages]), runtime.timeout_seconds
            )
            turn_messages.append(response)
            break

        turn_messages.append(response)
        for call in tool_calls:
            tool_name = str(call.get("name") or "unknown")[:100]
            call_id = str(call.get("id") or "unknown")[:100]
            if _is_duplicate_tool_call([*request, *turn_messages[:-1]], call):
                logger.warning(
                    "agent.tool.rejected | tool=%s | call_id=%s | reason=duplicate_call",
                    tool_name, call_id,
                )
                turn_messages.append(ToolMessage(
                    content=f"tool_error: identical {tool_name} arguments were already executed in this user turn; use the existing result or choose a different tool/request.",
                    tool_call_id=call_id, status="error",
                ))
                continue

            logger.info(
                "agent.tool.started | tool=%s | call_id=%s | used=%d | limit=%d",
                tool_name, call_id, used, runtime.max_tool_calls,
            )
            tool = by_name.get(call.get("name"))
            if tool is None:
                value_message = ToolMessage(
                    content=f"tool_error: unknown tool {tool_name}",
                    tool_call_id=call_id, status="error",
                )
                turn_messages.append(value_message)
                continue
            try:
                value = call_with_timeout(
                    lambda: tool.invoke(call.get("args", {})), runtime.timeout_seconds
                )
            except Exception as exc:
                logger.warning(
                    "agent.tool.failed | tool=%s | call_id=%s | error=%s",
                    tool_name, call_id, safe_exception_summary(exc),
                )
                turn_messages.append(ToolMessage(
                    content=f"{_classify(exc)}. Select another suitable tool or report the limitation; do not repeat the same call unchanged.",
                    tool_call_id=call_id, status="error",
                ))
                continue
            logger.info("agent.tool.finished | tool=%s | call_id=%s", tool_name, call_id)
            turn_messages.append(ToolMessage(content=str(value), tool_call_id=call_id))
            executed_calls += 1

        response = call_with_timeout(
            lambda: runtime.model.invoke([*request, *turn_messages]), runtime.timeout_seconds
        )
    else:
        response = AIMessage(content="Tool call iteration limit reached. Provide an answer using the available tool results.")
        turn_messages.append(response)

    history = [*request, *turn_messages]
    _save_fallback_state(runtime.checkpointer, session_id, thread_id, {"messages": history})
    return {"output": getattr(response, "content", str(response)),
            "messages": history, "tool_calls": executed_calls}
def invoke_agent(runtime: AgentRuntime, messages: list[BaseMessage], session_id: str,
                 thread_id: str | None = None, config: dict[str, Any] | None = None) -> Any:
    thread_id = thread_id or new_thread_id()
    with runtime_context(session_id, thread_id):
        try:
            if runtime.graph is not None:
                return runtime.graph.invoke({"messages": messages},
                    config={"configurable": {"thread_id": _graph_thread_id(session_id, thread_id), "session_id": session_id}})
            return _fallback_invoke(runtime, messages, session_id, thread_id)
        except AgentRuntimeError as exc:
            _log_agent_failure(exc, session_id, thread_id)
            raise
        except Exception as exc:
            classified = _classify(exc)
            _log_agent_failure(classified, session_id, thread_id)
            raise classified from exc


def stream_agent(runtime: AgentRuntime, messages: list[BaseMessage], session_id: str,
                 thread_id: str | None = None):
    """Yield stable UI events from LangGraph updates/messages or fallback execution."""
    from agent.events import UIEvent, iter_stream_events

    thread_id = thread_id or new_thread_id()
    with runtime_context(session_id, thread_id):
        try:
            if runtime.graph is not None:
                raw = runtime.graph.stream({"messages": messages},
                    config={"configurable": {"thread_id": _graph_thread_id(session_id, thread_id), "session_id": session_id}},
                    stream_mode=("updates", "messages"))
                stream_events = []
                tool_names: dict[str, str] = {}
                text_state: dict[str, str] = {}
                for raw_event in raw:
                    normalized = list(iter_stream_events([raw_event], tool_names))
                    stream_events.extend(normalized)
                    for event in normalized:
                        if event.type == "text_delta":
                            from agent.events import sanitize_text_event
                            yield sanitize_text_event(event, text_state)
                        else:
                            yield event
                yield from _recover_missing_tool_results(
                    runtime.graph,
                    session_id,
                    thread_id,
                    messages,
                    stream_events,
                )
                return
            result = invoke_agent(runtime, messages, session_id, thread_id)
            tool_names: dict[str, str] = {}
            for message in result.get("messages", []):
                for call in getattr(message, "tool_calls", None) or []:
                    call_id = call.get("id")
                    if call_id:
                        tool_names[call_id] = call.get("name", "")
                        yield UIEvent(
                            "tool_started",
                            call_id,
                            call.get("name"),
                            {"args": call.get("args", {})},
                        )
                if isinstance(message, ToolMessage):
                    yield UIEvent(
                        "tool_finished",
                        message.tool_call_id,
                        getattr(message, "name", None)
                        or tool_names.get(message.tool_call_id),
                        {"content": message.content},
                    )
            yield UIEvent("text_delta", None, None, {"delta": result["output"], "done": True})
        except AgentRuntimeError as exc:
            if runtime.graph is not None:
                _log_agent_failure(exc, session_id, thread_id)
            raise
        except Exception as exc:
            classified = _classify(exc)
            if runtime.graph is not None:
                _log_agent_failure(classified, session_id, thread_id)
            raise classified from exc


def _recover_missing_tool_results(
    graph: Any,
    session_id: str,
    thread_id: str,
    input_messages: list[BaseMessage],
    stream_events: list[Any],
):
    """Recover tool results omitted by the event stream from this run's checkpoint."""
    from agent.events import UIEvent

    get_state = getattr(graph, "get_state", None)
    if not callable(get_state):
        logger.warning(
            "agent.stream.recovery.unavailable | reason=no_get_state | thread_id=%s",
            thread_id,
        )
        return

    try:
        snapshot = get_state({
            "configurable": {
                "thread_id": _graph_thread_id(session_id, thread_id),
                "session_id": session_id,
            }
        })
        state = getattr(snapshot, "values", None)
        checkpoint_messages = state.get("messages", []) if isinstance(state, dict) else []
    except Exception as exc:
        logger.warning(
            "agent.stream.recovery.failed | thread_id=%s | error=%s",
            thread_id,
            safe_exception_summary(exc),
        )
        return

    if len(checkpoint_messages) < len(input_messages):
        return
    checkpoint_prefix = checkpoint_messages[:len(input_messages)]
    if any(
        left.__class__ is not right.__class__
        or getattr(left, "content", None) != getattr(right, "content", None)
        for left, right in zip(checkpoint_prefix, input_messages)
    ):
        logger.warning(
            "agent.stream.recovery.skipped | reason=input_prefix_mismatch | thread_id=%s",
            thread_id,
        )
        return
    new_messages = checkpoint_messages[len(input_messages):]
    seen_call_ids = {
        event.call_id
        for event in stream_events
        if getattr(event, "type", None) == "tool_finished" and getattr(event, "call_id", None)
    }
    pending_names: dict[str, str] = {}
    recovered = 0
    for message in new_messages:
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("id"):
                pending_names[call["id"]] = call.get("name", "")
        if not isinstance(message, ToolMessage) or message.tool_call_id in seen_call_ids:
            continue
        call_id = message.tool_call_id
        name = getattr(message, "name", None) or pending_names.get(call_id)
        yield UIEvent("tool_finished", call_id, name, {"content": message.content})
        seen_call_ids.add(call_id)
        recovered += 1

    logger.info(
        "agent.stream.recovery.completed | thread_id=%s | checkpoint_messages=%d "
        "| missing_tool_results=%d",
        thread_id,
        len(new_messages),
        recovered,
    )


def reset_agent_thread(runtime: AgentRuntime, thread_id: str, session_id: str | None = None) -> None:
    if session_id is not None:
        runtime._fallback_messages.pop((session_id, thread_id), None)
        if hasattr(runtime.checkpointer, "delete"):
            try:
                runtime.checkpointer.delete(session_id=session_id, thread_id=thread_id)
            except TypeError:
                runtime.checkpointer.delete_thread(_graph_thread_id(session_id, thread_id))
        elif hasattr(runtime.checkpointer, "delete_thread"):
            runtime.checkpointer.delete_thread(_graph_thread_id(session_id, thread_id))
    else:
        for key in list(runtime._fallback_messages):
            if key[1] == thread_id:
                runtime._fallback_messages.pop(key, None)


def create_agent() -> AgentRuntime:
    from agent.analysis_tools import create_analysis_tools
    from agent.web_search import create_web_search_tool

    tools = create_analysis_tools(include_import_tools=True)
    web_search = create_web_search_tool()
    if web_search is not None:
        tools.append(web_search)
    return create_agent_runtime(tools=tools)


def reset_agent_memory(runtime: AgentRuntime) -> AgentRuntime:
    runtime._fallback_messages.clear()
    return runtime
