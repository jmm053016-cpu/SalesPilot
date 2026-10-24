from __future__ import annotations

from decimal import Decimal

from models.analysis import MetricValue
from agent.events import UIEvent
from ui.analysis_view import metric_availability_text, summarize_tool_events
from ui.session import (
    AnalysisSession,
    artifact_download_ref,
    create_analysis_session,
    reset_analysis_thread,
)


def test_analysis_session_initializes_with_isolated_thread() -> None:
    session = create_analysis_session("session-a")

    assert isinstance(session, AnalysisSession)
    assert session.session_id == "session-a"
    assert session.dataset_id is None
    assert session.analysis_id is None
    assert session.report_ids == []
    assert session.thread_id


def test_reset_thread_preserves_data_references_but_changes_thread_id() -> None:
    session = AnalysisSession(
        session_id="session-a",
        dataset_id="dataset-a",
        analysis_id="analysis-a",
        report_ids=["artifact-a"],
        thread_id="thread-old",
    )

    reset = reset_analysis_thread(session)

    assert reset.session_id == session.session_id
    assert reset.dataset_id == session.dataset_id
    assert reset.analysis_id == session.analysis_id
    assert reset.report_ids == session.report_ids
    assert reset.thread_id != "thread-old"


def test_artifact_download_reference_uses_server_artifact_id() -> None:
    reference = artifact_download_ref(
        artifact_id="artifact-a",
        display_name="sales-report.pdf",
        mime_type="application/pdf",
    )

    assert reference == {
        "artifact_id": "artifact-a",
        "display_name": "sales-report.pdf",
        "mime_type": "application/pdf",
    }


def test_unavailable_metric_shows_reason_instead_of_dash_only() -> None:
    metric = MetricValue(value=None, unit="currency", reason="cost_amount is missing")

    assert metric_availability_text(metric) == "不可用：cost_amount is missing"


def test_tool_event_summary_uses_ui_events_not_intermediate_steps() -> None:
    events = [
        UIEvent("tool_started", "call-a", "inspect_dataset", {"args": {"dataset_id": "d1"}}),
        UIEvent("tool_finished", "call-a", "inspect_dataset", {"content": "ready"}),
        UIEvent("tool_failed", "call-b", "run_sales_analysis", {
            "category": "validation_error",
            "message": "invalid request",
        }),
    ]

    summary = summarize_tool_events(events)

    assert summary == [
        {"call_id": "call-a", "name": "inspect_dataset", "status": "done"},
        {"call_id": "call-b", "name": "run_sales_analysis", "status": "error", "message": "invalid request"},
    ]
