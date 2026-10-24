from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from agent.events import UIEvent, adapt_stream_events
from ui.session import create_analysis_session
from ui.workbench import apply_agent_resource_events


def test_updates_match_tool_completion_by_call_id_not_last_history_item() -> None:
    raw_events = [
        (
            "model",
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"id": "call-a", "name": "inspect_dataset", "args": {"dataset_id": "d1"}},
                            {"id": "call-b", "name": "run_sales_analysis", "args": {"dataset_id": "d1"}},
                        ],
                    )
                ]
            },
        ),
        ("tools", {"messages": [ToolMessage(content="analysis done", tool_call_id="call-b")]}),
        ("tools", {"messages": [ToolMessage(content="dataset ready", tool_call_id="call-a")]}),
    ]

    events = adapt_stream_events(raw_events)

    finished = [event for event in events if event.type == "tool_finished"]
    assert [(event.call_id, event.name) for event in finished] == [
        ("call-b", "run_sales_analysis"),
        ("call-a", "inspect_dataset"),
    ]
    assert finished[-1].payload["content"] == "dataset ready"


def test_langgraph_node_wrapped_updates_emit_tool_results_for_resource_binding() -> None:
    raw_events = [
        ("updates", {"model": {"messages": [AIMessage(
            content="",
            tool_calls=[{
                "id": "call-save", "name": "validate_and_save_dataset", "args": {}
            }],
        )]}}),
        ("updates", {"tools": {"messages": [ToolMessage(
            content='{"ok":true,"status":"dataset_saved","dataset_id":"ds_saved"}',
            tool_call_id="call-save",
        )]}}),
    ]

    events = adapt_stream_events(raw_events)

    assert [(event.type, event.name) for event in events] == [
        ("tool_started", "validate_and_save_dataset"),
        ("tool_finished", "validate_and_save_dataset"),
    ]
    assert events[-1].call_id == "call-save"


def test_langgraph_save_and_analysis_messages_bind_resources_to_session() -> None:
    raw_events = [
        ("updates", {"model": {"messages": [AIMessage(
            content="",
            tool_calls=[{
                "id": "call-save", "name": "validate_and_save_dataset", "args": {}
            }],
        )]}}),
        ("updates", {"tools": {"messages": [ToolMessage(
            content='{"ok":true,"status":"dataset_saved","dataset_id":"ds_saved"}',
            tool_call_id="call-save",
        )]}}),
        ("updates", {"model": {"messages": [AIMessage(
            content="",
            tool_calls=[{
                "id": "call-analysis", "name": "run_sales_analysis", "args": {}
            }],
        )]}}),
        ("updates", {"tools": {"messages": [ToolMessage(
            content='{"ok":true,"analysis_id":"analysis_done","dataset_id":"ds_saved","rankings":[]}',
            tool_call_id="call-analysis",
        )]}}),
    ]

    events = adapt_stream_events(raw_events)
    updated = apply_agent_resource_events(create_analysis_session("session-events"), events)

    assert updated.dataset_id == "ds_saved"
    assert updated.analysis_id == "analysis_done"


def test_v2_update_events_bind_saved_dataset_and_analysis() -> None:
    raw_events = [
        {
            "type": "updates",
            "data": {"model": {"messages": [AIMessage(
                content="",
                tool_calls=[{
                    "id": "call-save-v2", "name": "validate_and_save_dataset", "args": {}
                }],
            )]}},
        },
        {
            "type": "updates",
            "data": {"tools": {"messages": [ToolMessage(
                content='{"ok":true,"status":"dataset_saved","dataset_id":"ds_v2"}',
                tool_call_id="call-save-v2",
            )]}},
        },
        {
            "type": "updates",
            "data": {"model": {"messages": [AIMessage(
                content="",
                tool_calls=[{
                    "id": "call-analysis-v2", "name": "run_sales_analysis", "args": {}
                }],
            )]}},
        },
        {
            "type": "updates",
            "data": {"tools": {"messages": [ToolMessage(
                content='{"ok":true,"analysis_id":"analysis_v2","dataset_id":"ds_v2"}',
                tool_call_id="call-analysis-v2",
            )]}},
        },
    ]

    events = adapt_stream_events(raw_events)
    updated = apply_agent_resource_events(create_analysis_session("session-v2"), events)

    assert updated.dataset_id == "ds_v2"
    assert updated.analysis_id == "analysis_v2"


def test_serialized_langchain_messages_bind_saved_dataset_and_analysis() -> None:
    raw_events = [
        ("updates", {"tools": {"messages": [{
            "type": "ai", "data": {"content": "", "tool_calls": [{
                "id": "call-save-serialized", "name": "validate_and_save_dataset", "args": {}
            }]},
        }]}}),
        ("updates", {"tools": {"messages": [{
            "type": "tool", "data": {
                "content": '{"ok":true,"status":"dataset_saved","dataset_id":"ds_serialized"}',
                "tool_call_id": "call-save-serialized", "name": "validate_and_save_dataset",
            },
        }]}}),
        ("updates", {"tools": {"messages": [{
            "type": "ai", "data": {"content": "", "tool_calls": [{
                "id": "call-analysis-serialized", "name": "run_sales_analysis", "args": {}
            }]},
        }]}}),
        ("updates", {"tools": {"messages": [{
            "type": "tool", "data": {
                "content": '{"ok":true,"analysis_id":"analysis_serialized","dataset_id":"ds_serialized"}',
                "tool_call_id": "call-analysis-serialized", "name": "run_sales_analysis",
            },
        }]}}),
    ]

    events = adapt_stream_events(raw_events)
    updated = apply_agent_resource_events(create_analysis_session("session-serialized"), events)

    assert [event.type for event in events] == [
        "tool_started", "tool_finished", "tool_started", "tool_finished"
    ]
    assert updated.dataset_id == "ds_serialized"
    assert updated.analysis_id == "analysis_serialized"


def test_messages_stream_is_emitted_as_text_deltas_and_accumulates() -> None:
    raw_events = [
        (AIMessageChunk(content="销售"), {"langgraph_node": "model"}),
        (AIMessageChunk(content="额上升"), {"langgraph_node": "model"}),
        (AIMessageChunk(content="。"), {"langgraph_node": "model", "finish_reason": "stop"}),
    ]

    events = adapt_stream_events(raw_events)

    assert [event.type for event in events] == ["text_delta", "text_delta", "text_delta"]
    assert "".join(event.payload["delta"] for event in events) == "销售额上升。"
    assert events[-1].payload["done"] is True


def test_tool_error_is_classified_and_keeps_call_id() -> None:
    raw_events = [
        {
            "type": "tool_error",
            "call_id": "call-a",
            "name": "inspect_dataset",
            "error": {"category": "validation_error", "message": "unknown dataset"},
        }
    ]

    events = adapt_stream_events(raw_events)

    assert events == [
        UIEvent(
            type="tool_failed",
            call_id="call-a",
            name="inspect_dataset",
            payload={
                "category": "validation_error",
                "message": "unknown dataset",
            },
        )
    ]


def test_run_end_marks_terminal_state_without_using_last_history_record() -> None:
    raw_events = [
        {"type": "text", "content": "完成"},
        {"type": "run_end", "status": "success", "message_count": 7},
    ]

    events = adapt_stream_events(raw_events)

    assert events[-1].type == "text_delta"
    assert events[-1].payload == {
        "delta": "",
        "done": True,
        "status": "success",
        "message_count": 7,
    }


def test_sanitize_text_event_hides_serialized_tool_payloads():
    from agent.events import sanitize_text_event

    state = {}
    first = sanitize_text_event(UIEvent("text_delta", None, None, {
        "delta": "先检查 "
    }), state)
    second = sanitize_text_event(UIEvent("text_delta", None, None, {
        "delta": "{'ok': True, 'dataset_id': 'ds-a'}"
    }), state)
    third = sanitize_text_event(UIEvent("text_delta", None, None, {
        "delta": "，结果已完成。"
    }), state)

    assert first.payload["delta"] == "先检查 "
    assert second.payload["delta"] == ""
    assert third.payload["delta"] == "，结果已完成。"
