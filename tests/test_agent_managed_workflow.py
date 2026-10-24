from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

from agent.events import UIEvent
from agent.analysis_tools import create_analysis_tools
from agent.context import runtime_context
from models.analysis import AnalysisRequest
from storage.analyses import AnalysisStore
from storage.datasets import DatasetStore
from storage.uploads import UploadStore
from ui.session import create_analysis_session
from ui.workbench import (
    AgentManagedWorkflowError,
    apply_agent_resource_events,
    execute_agent_managed_workflow,
)


def test_agent_tool_results_bind_dataset_and_analysis_to_session():
    session = create_analysis_session("session-agent")
    events = [
        UIEvent(
            "tool_finished", "call-dataset", "validate_and_save_dataset",
            {"content": json.dumps({"ok": True, "dataset_id": "ds_saved"})},
        ),
        UIEvent(
            "tool_finished", "call-analysis", "run_sales_analysis",
            {"content": json.dumps({"ok": True, "analysis_id": "analysis_done"})},
        ),
    ]

    updated = apply_agent_resource_events(session, events)

    assert updated.dataset_id == "ds_saved"
    assert updated.analysis_id == "analysis_done"
    assert session.dataset_id is None
    assert session.analysis_id is None


def test_failed_agent_tool_does_not_replace_existing_resource_bindings():
    session = create_analysis_session("session-agent")
    session = replace(session, dataset_id="ds_existing", analysis_id="analysis_existing")
    events = [
        UIEvent(
            "tool_finished", "call-analysis", "run_sales_analysis",
            {"content": json.dumps({"ok": False, "error": {"category": "invalid_request"}})},
        ),
    ]

    updated = apply_agent_resource_events(session, events)

    assert updated.dataset_id == "ds_existing"
    assert updated.analysis_id == "analysis_existing"


def test_agent_resource_binding_uses_tool_started_name_when_finish_name_is_missing():
    session = create_analysis_session("session-agent")
    events = [
        UIEvent("tool_started", "call-dataset", "validate_and_save_dataset", {}),
        UIEvent(
            "tool_finished", "call-dataset", None,
            {"content": {"ok": True, "dataset_id": "ds_streamed"}},
        ),
        UIEvent("tool_started", "call-analysis", "run_sales_analysis", {}),
        UIEvent(
            "tool_finished", "call-analysis", None,
            {"content": {"ok": True, "analysis_id": "analysis_streamed"}},
        ),
    ]

    updated = apply_agent_resource_events(session, events)

    assert updated.dataset_id == "ds_streamed"
    assert updated.analysis_id == "analysis_streamed"


def test_agent_resource_binding_uses_success_payload_without_tool_metadata():
    session = create_analysis_session("session-agent")
    events = [
        UIEvent(
            "tool_finished", None, None,
            {"content": {"ok": True, "status": "dataset_saved", "dataset_id": "ds_saved"}},
        ),
        UIEvent(
            "tool_finished", None, None,
            {"content": {"ok": True, "analysis_id": "analysis_done", "dataset_id": "ds_saved"}},
        ),
    ]

    updated = apply_agent_resource_events(session, events)

    assert updated.dataset_id == "ds_saved"
    assert updated.analysis_id == "analysis_done"


def test_agent_workflow_sends_source_and_goal_to_current_session_thread():
    session = create_analysis_session("session-agent")
    seen = {}

    def fake_stream(agent, messages, session_id, thread_id):
        seen.update(
            agent=agent,
            prompt=messages[0].content,
            session_id=session_id,
            thread_id=thread_id,
        )
        return iter([
            UIEvent(
                "tool_finished", "call-dataset", "validate_and_save_dataset",
                {"content": {"ok": True, "dataset_id": "ds_saved"}},
            )
        ])

    updated, events = execute_agent_managed_workflow(
        "agent", session, "src_123", "按品类分析销售额", stream=fake_stream
    )

    assert seen["agent"] == "agent"
    assert seen["session_id"] == session.session_id
    assert seen["thread_id"] == session.thread_id
    assert "src_123" in seen["prompt"]
    assert "按品类分析销售额" in seen["prompt"]
    assert "默认按净销售额" in seen["prompt"]
    assert "comparison=none" in seen["prompt"]
    assert "coverage=unknown 不得阻止分析完成" in seen["prompt"]
    assert "change=null 只表示变化率不可用" in seen["prompt"]
    assert "不要输出原始 JSON" in seen["prompt"]
    assert "只回复关键结论和必要限制" in seen["prompt"]
    assert updated.dataset_id == "ds_saved"
    assert len(events) == 1


def test_agent_workflow_preserves_successful_analysis_when_final_stream_fails():
    session = create_analysis_session("session-partial")
    completed = UIEvent(
        "tool_finished", "call-analysis", "run_sales_analysis",
        {"content": {"ok": True, "dataset_id": "ds_saved", "analysis_id": "analysis_done"}},
    )

    def failed_stream(*_args):
        yield completed
        raise RuntimeError("tool_limit: tool call limit exceeded")

    try:
        execute_agent_managed_workflow(
            object(), session, "src_123", "分析销售额", stream=failed_stream
        )
    except AgentManagedWorkflowError as exc:
        assert exc.session.dataset_id == "ds_saved"
        assert exc.session.analysis_id == "analysis_done"
        assert exc.events == [completed]
        assert "tool_limit" in str(exc)
    else:
        raise AssertionError("stream failure should be surfaced with its partial results")


def test_agent_workflow_resets_stale_checkpoint_before_streaming(monkeypatch):
    from agent import agent_setup

    session = create_analysis_session("session-agent")
    calls = []

    def fake_reset(runtime, thread_id, session_id):
        calls.append(("reset", runtime, thread_id, session_id))

    def fake_stream(runtime, messages, session_id, thread_id):
        calls.append(("stream", runtime, thread_id, session_id))
        return iter([])

    monkeypatch.setattr(agent_setup, "reset_agent_thread", fake_reset)

    execute_agent_managed_workflow(
        SimpleNamespace(checkpointer=object(), _fallback_messages={}),
        session,
        "src_123",
        "分析销售额",
        stream=fake_stream,
    )

    assert calls == [
        ("reset", calls[0][1], session.thread_id, session.session_id),
        ("stream", calls[0][1], session.thread_id, session.session_id),
    ]


def test_uploaded_csv_is_saved_analyzed_and_restored_from_stores(tmp_path):
    session_id = "session-e2e"
    upload_store = UploadStore(tmp_path / "uploads")
    source = upload_store.save(
        session_id,
        "sales.csv",
        b"date,amount\n2024-01-01,12.50\n2024-01-02,18.00\n",
        "upload-key",
    )
    dataset_root = tmp_path / "datasets"
    analysis_root = tmp_path / "analyses"
    dataset_store = DatasetStore(dataset_root)
    analysis_store = AnalysisStore(analysis_root)
    tools = create_analysis_tools(
        dataset_store=dataset_store,
        upload_store=upload_store,
        analysis_root=analysis_root,
        include_import_tools=True,
    )
    by_name = {tool.name: tool for tool in tools}

    def fake_stream(_agent, _messages, current_session_id, thread_id):
        assert current_session_id == session_id
        with runtime_context(current_session_id, thread_id):
            inspected = by_name["inspect_import_source"].invoke({"source_id": source.source_id})
            assert inspected["ok"] is True
            saved = by_name["validate_and_save_dataset"].invoke({
                "source_id": source.source_id,
                "mapping_json": json.dumps({"date": "order_date", "amount": "sales_amount"}),
                "options_json": json.dumps({"grain": "aggregate", "currency": "USD"}),
                "idempotency_key": "import-task",
            })
            analysis = by_name["run_sales_analysis"].invoke({
                "dataset_id": saved["dataset_id"],
                "request_json": json.dumps({
                    "current_start": "2024-01-01",
                    "current_end": "2024-01-02",
                    "comparison": "none",
                    "group_by": [],
                }),
            })
        return iter([
            UIEvent("tool_finished", "save", "validate_and_save_dataset", {"content": saved}),
            UIEvent("tool_finished", "analysis", "run_sales_analysis", {"content": analysis}),
        ])

    session = create_analysis_session(session_id)
    updated, events = execute_agent_managed_workflow(
        object(), session, source.source_id, "分析销售额", stream=fake_stream
    )

    assert updated.dataset_id == events[0].payload["content"]["dataset_id"]
    assert updated.analysis_id == events[1].payload["content"]["analysis_id"]
    assert DatasetStore(dataset_root).load(session_id, updated.dataset_id).shape == (2, 2)
    restored = AnalysisStore(analysis_root).get(session_id, updated.analysis_id)
    assert restored["metrics"]["sales"]["value"] == "30.50"
