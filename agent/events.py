"""将 LangChain 更新与消息流归一为稳定的界面事件结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class UIEvent:
    type: Literal["text_delta", "tool_started", "tool_finished", "tool_failed"]
    call_id: str | None
    name: str | None
    payload: dict[str, Any]


def _message_content(message: Any) -> str:
    content = _message_data(message).get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content)
    return str(content or "")


def _tool_call_id(message: Any) -> str | None:
    data = _message_data(message)
    return data.get("tool_call_id") or data.get("id")


def _message_data(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        data = message.get("data")
        return data if isinstance(data, dict) else message
    return {
        "content": getattr(message, "content", ""),
        "tool_call_id": getattr(message, "tool_call_id", None),
        "id": getattr(message, "id", None),
        "name": getattr(message, "name", None),
        "tool_calls": getattr(message, "tool_calls", None),
    }


def _message_kind(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("type") or message.get("role") or "").lower()
    return message.__class__.__name__.lower()


def _updated_messages(payload: dict[str, Any]) -> list[Any]:
    """Collect messages from both flat and LangGraph node-wrapped updates."""
    messages: list[Any] = []

    def visit(value: Any) -> None:
        if not isinstance(value, dict):
            return
        node_messages = value.get("messages")
        if isinstance(node_messages, list):
            messages.extend(node_messages)
        for key, nested in value.items():
            if key != "messages" and isinstance(nested, dict):
                visit(nested)

    visit(payload)
    return messages


def iter_stream_events(raw_events: Any, tool_names: dict[str, str] | None = None):
    """Convert LangGraph updates/messages and internal error events to UI events."""
    if tool_names is None:
        tool_names = {}
    for raw in raw_events:
        if isinstance(raw, dict):
            event_type = raw.get("type")
            if event_type == "tool_error":
                error = raw.get("error") or {}
                yield UIEvent("tool_failed", raw.get("call_id"), raw.get("name"), {
                    "category": error.get("category", "tool_error"), "message": error.get("message", str(error))
                })
            elif event_type == "text":
                yield UIEvent("text_delta", None, None, {"delta": raw.get("content", ""), "done": False})
            elif event_type == "run_end":
                yield UIEvent("text_delta", None, None, {
                    "delta": "", "done": True, "status": raw.get("status"), "message_count": raw.get("message_count")
                })
            elif event_type in {"updates", "messages"}:
                payload = raw.get("data", raw.get("payload"))
                if isinstance(payload, dict):
                    for message in _updated_messages(payload):
                        data = _message_data(message)
                        for call in data.get("tool_calls") or []:
                            if call.get("id"):
                                tool_names[call["id"]] = call.get("name")
                            yield UIEvent("tool_started", call.get("id"), call.get("name"), {"args": call.get("args", {})})
                        if _message_kind(message) in {"tool", "toolmessage"}:
                            call_id = _tool_call_id(message)
                            yield UIEvent("tool_finished", call_id, data.get("name") or tool_names.get(call_id), {
                                "content": _message_content(message)
                            })
                        elif _message_content(message):
                            yield UIEvent("text_delta", None, None, {"delta": _message_content(message), "done": False})
            continue
        if not isinstance(raw, tuple) or len(raw) != 2:
            continue
        mode, payload = raw
        if hasattr(mode, "content") and isinstance(payload, dict):
            content = _message_content(mode)
            if content:
                yield UIEvent("text_delta", None, None, {
                    "delta": content, "done": bool(payload.get("finish_reason"))
                })
            continue
        if hasattr(payload, "content"):
            content = _message_content(payload)
            if content:
                metadata = raw[1] if isinstance(raw[1], dict) else getattr(payload, "response_metadata", {}) or {}
                yield UIEvent("text_delta", None, None, {
                    "delta": content, "done": bool(metadata.get("finish_reason"))
                })
            continue
        if not isinstance(payload, dict):
            continue
        for message in _updated_messages(payload):
            data = _message_data(message)
            for call in data.get("tool_calls") or []:
                if call.get("id"):
                    tool_names[call["id"]] = call.get("name")
                yield UIEvent("tool_started", call.get("id"), call.get("name"), {"args": call.get("args", {})})
            if _message_kind(message) in {"tool", "toolmessage"}:
                call_id = _tool_call_id(message)
                yield UIEvent("tool_finished", call_id, data.get("name") or tool_names.get(call_id), {
                    "content": _message_content(message)
                })
            elif _message_content(message):
                yield UIEvent("text_delta", None, None, {"delta": _message_content(message), "done": False})












def _matching_object_end(text: str, start: int) -> int | None:
    """Return the matching closing brace while respecting quoted strings."""
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"\"", "'"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def sanitize_assistant_text(text: str) -> str:
    """Remove serialized tool-result dictionaries from assistant-visible text."""
    import re

    parts: list[str] = []
    index = 0
    while index < len(text):
        if text[index] != "{":
            parts.append(text[index])
            index += 1
            continue
        end = _matching_object_end(text, index)
        if end is None:
            # A streamed object may be incomplete; keep it hidden until complete.
            break
        candidate = text[index:end + 1]
        if not re.match(r"^\{\s*(?:'ok'|\"ok\")\s*:", candidate):
            parts.append(candidate)
        index = end + 1
    return "".join(parts)


def sanitize_text_event(event: UIEvent, state: dict[str, str]) -> UIEvent:
    """Incrementally redact tool-result objects without interrupting plain text."""
    if event.type != "text_delta":
        return event
    state["raw"] = state.get("raw", "") + str(event.payload.get("delta", ""))
    safe_text = sanitize_assistant_text(state["raw"])
    previous = state.get("visible", "")
    delta = safe_text[len(previous):] if safe_text.startswith(previous) else ""
    if safe_text.startswith(previous):
        state["visible"] = safe_text
    payload = {**event.payload, "delta": delta}
    return UIEvent(event.type, event.call_id, event.name, payload)


def adapt_stream_events(raw_events: Any) -> list[UIEvent]:
    return list(iter_stream_events(raw_events))
