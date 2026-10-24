from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import sys

import pytest

from models.analysis import AnalysisRequest, AnalysisResult, MetricValue
from models.report import ArtifactRef, ReportModel, NarrativeResult
from models.sales import DateRange
from storage.artifacts import ArtifactStore
from ui.session import create_analysis_session


def result():
    return AnalysisResult(
        analysis_id="analysis_ui", dataset_id="ds_ui",
        request=AnalysisRequest(dataset_id="ds_ui", current_start=date(2024, 1, 1),
            current_end=date(2024, 1, 31), comparison="none", group_by=[]),
        metrics={"sales": MetricValue(value=Decimal("120.50"), unit="USD"),
            "gross_profit": MetricValue(value=None, unit="USD", reason="cost_amount is missing")},
    )


class Screen:
    def __init__(self, state=None):
        self.session_state = state or {}
        self.calls = []

    def __getattr__(self, name):
        def capture(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return capture


def test_result_page_shows_missing_capability_and_empty_sections(monkeypatch):
    from ui.analysis_view import render_analysis_result
    screen = Screen()
    monkeypatch.setitem(sys.modules, "streamlit", screen)
    render_analysis_result(result(), None)
    text = str(screen.calls)
    assert "120.50" in text
    assert "cost_amount is missing" in text
    assert "暂无期间对比" in text
    assert "暂无排名" in text
    assert "暂无异常" in text
    assert "解读暂不可用" in text
    assert not any(call[0] == "download_button" for call in screen.calls)


def test_result_page_download_resolves_artifact_for_current_session(tmp_path, monkeypatch):
    from ui.analysis_view import render_analysis_result
    analysis = result()
    path = tmp_path / "report.pdf"
    path.write_bytes(b"report bytes")
    ref = ArtifactRef(artifact_id="artifact_ui", kind="report", mime_type="application/pdf",
        display_name="report.pdf", storage_key=str(path))
    store = ArtifactStore(tmp_path / "artifacts")
    store.register("session_a", ref.artifact_id, ref)
    report = ReportModel(report_id="report_ui", analysis_id=analysis.analysis_id,
        dataset_id=analysis.dataset_id, period=DateRange(start=analysis.request.current_start,
        end=analysis.request.current_end), artifacts=[ref], narrative=NarrativeResult(
            summary="销售额为 120.50 USD。", recommendations=[{"text": "关注销售表现", "evidence_ids": ["ev_sales"]}],
            hypotheses=["区域差异需验证"], status="generated"))
    screen = Screen({"analysis_session": create_analysis_session("session_a"), "artifact_store": store})
    monkeypatch.setitem(sys.modules, "streamlit", screen)
    render_analysis_result(analysis, report)
    downloads = [call for call in screen.calls if call[0] == "download_button"]
    assert len(downloads) == 1
    assert downloads[0][2]["data"] == b"report bytes"
    assert downloads[0][2]["file_name"] == "report.pdf"
    assert "关注销售表现" in str(screen.calls)
    assert "区域差异需验证" in str(screen.calls)

    screen.session_state["analysis_session"] = create_analysis_session("session_b")
    screen.calls.clear()
    render_analysis_result(analysis, report)
    assert not any(call[0] == "download_button" for call in screen.calls)
    assert any(call[0] == "warning" for call in screen.calls)


def test_result_page_rejects_report_from_another_analysis(monkeypatch):
    from ui.analysis_view import render_analysis_result
    screen = Screen()
    monkeypatch.setitem(sys.modules, "streamlit", screen)
    report = ReportModel(report_id="report_other", analysis_id="other", dataset_id="ds_ui",
        period=DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31)))
    with pytest.raises(ValueError, match="report"):
        render_analysis_result(result(), report)
    assert screen.calls == []


def test_result_page_shows_model_failure_reason_instead_of_blame_on_missing_key(monkeypatch):
    from ui.analysis_view import render_analysis_result
    analysis = result()
    report = ReportModel(report_id="report_fallback", analysis_id=analysis.analysis_id,
        dataset_id=analysis.dataset_id, period=DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31)),
        narrative=NarrativeResult(summary="facts", status="fallback", diagnostic="HTTP 400: invalid model request"))
    screen = Screen()
    monkeypatch.setitem(sys.modules, "streamlit", screen)

    render_analysis_result(analysis, report)

    text = str(screen.calls)
    assert "HTTP 400: invalid model request" in text
    assert "DEEPSEEK_API_KEY" not in text
