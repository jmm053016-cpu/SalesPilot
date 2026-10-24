from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from models.analysis import AnalysisRequest
from models.sales import DatasetProfile, DateRange, ImportOptions
from storage.analyses import AnalysisStore, UnauthorizedAnalysisError
from storage.artifacts import ArtifactStore, UnauthorizedArtifactError
from workflow.business_report import run_business_report


def _attach_log_capture(caplog, name: str):
    import logging

    logger = logging.getLogger(name)
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.INFO)
    return logger


def _profile(session_id: str, dataset_id: str = "ds_source") -> DatasetProfile:
    return DatasetProfile(dataset_id=dataset_id, session_id=session_id, rows=2, columns=["order_date", "sales_amount", "category", "region"], grain="aggregate", currency="USD", min_date=date(2024, 1, 1), max_date=date(2024, 1, 2), available_metrics=["sales"], unavailable_metrics={})


def _request(dataset_id: str = "ds_source") -> AnalysisRequest:
    return AnalysisRequest(dataset_id=dataset_id, current_start=date(2024, 1, 1), current_end=date(2024, 1, 31), comparison="none", group_by=["category", "region"])


def _dataset() -> pd.DataFrame:
    return pd.DataFrame({"order_date": ["2024-01-01", "2024-01-02"], "sales_amount": [100, 200], "category": ["A", "B"], "region": ["US", "EU"]})


def test_analysis_and_artifact_stores_enforce_session_ownership(tmp_path):
    analysis_store = AnalysisStore(tmp_path / "analyses")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    analysis = {"analysis_id": "analysis_1", "dataset_id": "ds_1", "value": 1}
    analysis_store.save("session_a", "analysis_1", analysis)
    artifact_store.register("session_a", "artifact_1", {"kind": "report", "storage_key": "session_a/report.pdf"})

    assert analysis_store.get("session_a", "analysis_1")["value"] == 1
    assert artifact_store.resolve("session_a", "artifact_1")["kind"] == "report"
    with pytest.raises(UnauthorizedAnalysisError):
        analysis_store.get("session_b", "analysis_1")
    with pytest.raises(UnauthorizedArtifactError):
        artifact_store.resolve("session_b", "artifact_1")


def test_business_report_runs_fixed_pipeline_and_returns_artifacts(tmp_path):
    from storage.datasets import DatasetStore
    dataset_store = DatasetStore(tmp_path / "datasets")
    ref = dataset_store.save("session_a", _dataset(), _profile("session_a"))

    result = run_business_report("session_a", _request(ref.dataset_id), ["word"], dataset_store=dataset_store, output_root=tmp_path / "reports")

    assert result.analysis_id
    assert result.stage_status["analysis"] == "completed"
    assert result.stage_status["export"] == "completed"
    assert len(result.artifacts) == 1
    assert Path(result.artifacts[0].storage_key).exists()
    assert result.errors == []


def test_business_report_rejects_cross_session_dataset(tmp_path):
    from storage.datasets import DatasetStore
    dataset_store = DatasetStore(tmp_path / "datasets")
    ref = dataset_store.save("session_a", _dataset(), _profile("session_a"))

    result = run_business_report("session_b", _request(ref.dataset_id), ["word"], dataset_store=dataset_store, output_root=tmp_path / "reports")

    assert result.analysis_id is None
    assert result.stage_status["load"] == "failed"
    assert any("unauthorized" in error.lower() for error in result.errors)


def test_business_report_returns_analysis_and_report_for_ui(tmp_path):
    from storage.datasets import DatasetStore
    dataset_store = DatasetStore(tmp_path / "datasets")
    ref = dataset_store.save("session_a", _dataset(), _profile("session_a"))

    result = run_business_report("session_a", _request(ref.dataset_id), ["word"], dataset_store=dataset_store, output_root=tmp_path / "reports")

    # 前端需要拿到确定性结果与结构化报告，而不是只有 analysis_id
    assert result.analysis is not None
    assert result.report is not None
    assert result.analysis.analysis_id == result.analysis_id
    assert result.report.analysis_id == result.analysis_id
    assert result.report.dataset_id == ref.dataset_id
    # 产物在导出阶段才生成，必须回填到报告，否则结果页下载入口为空
    assert [item.artifact_id for item in result.report.artifacts] == [item.artifact_id for item in result.artifacts]


def test_business_report_leaves_analysis_empty_when_load_fails(tmp_path):
    from storage.datasets import DatasetStore
    dataset_store = DatasetStore(tmp_path / "datasets")
    ref = dataset_store.save("session_a", _dataset(), _profile("session_a"))

    result = run_business_report("session_b", _request(ref.dataset_id), ["word"], dataset_store=dataset_store, output_root=tmp_path / "reports")

    assert result.analysis is None
    assert result.report is None


def test_business_report_keeps_word_when_pdf_export_fails(tmp_path, monkeypatch):
    from storage.datasets import DatasetStore
    from reports import pdf_report
    dataset_store = DatasetStore(tmp_path / "datasets")
    ref = dataset_store.save("session_a", _dataset(), _profile("session_a"))

    def fail_pdf(*args, **kwargs):
        raise RuntimeError("PDF render failed")

    monkeypatch.setattr(pdf_report, "export_pdf", fail_pdf)
    result = run_business_report("session_a", _request(ref.dataset_id), ["word", "pdf"], dataset_store=dataset_store, output_root=tmp_path / "reports")

    assert result.stage_status["analysis"] == "completed"
    assert result.stage_status["export"] == "partial_failed"
    assert any(artifact.mime_type.endswith("wordprocessingml.document") for artifact in result.artifacts)
    assert any("PDF" in error or "pdf" in error for error in result.errors)


def test_business_report_logs_pipeline_stages_without_dataset_values(tmp_path, caplog):
    from storage.datasets import DatasetStore

    dataset_store = DatasetStore(tmp_path / "datasets")
    ref = dataset_store.save("session_a", _dataset(), _profile("session_a"))
    logger = _attach_log_capture(caplog, "salespilot.workflow.business_report")
    try:
        run_business_report("session_a", _request(ref.dataset_id), ["word"], dataset_store=dataset_store, output_root=tmp_path / "reports")
    finally:
        logger.removeHandler(caplog.handler)

    messages = " ".join(record.getMessage() for record in caplog.records)
    for event in ("dataset.load.completed", "analysis.run.completed", "charts.generate.completed", "narrative.generation.completed", "report.export.completed"):
        assert event in messages
    assert "100" not in messages
    assert "200" not in messages


def test_business_report_logs_load_failure_without_exception_details(tmp_path, caplog):
    from storage.datasets import DatasetStore

    store = DatasetStore(tmp_path / "datasets")
    ref = store.save("session_a", _dataset(), _profile("session_a"))
    logger = _attach_log_capture(caplog, "salespilot.workflow.business_report")
    try:
        run_business_report("session_b", _request(ref.dataset_id), ["word"], dataset_store=store, output_root=tmp_path / "reports")
    finally:
        logger.removeHandler(caplog.handler)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "dataset.load.failed" in messages
    assert "100" not in messages
