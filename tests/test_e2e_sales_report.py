from datetime import date
from decimal import Decimal
from pathlib import Path

from data_sources.csv_source import load_csv
from data_sources.mapper import map_columns
from data_sources.validator import validate_and_normalize
from models.analysis import AnalysisRequest
from models.sales import DateRange, ImportOptions
from reports.render_verify import verify_report_artifact
from storage.datasets import DatasetStore
from storage.analyses import AnalysisStore
from workflow.business_report import run_business_report


def test_complete_fixture_runs_csv_to_verified_word_and_pdf_reports(tmp_path, complete_sales_csv):
    options = ImportOptions(source_name=complete_sales_csv.name, grain="order_line", currency="USD")
    raw = load_csv(complete_sales_csv, options)
    mapping = map_columns(raw.df, {})
    frame, validation = validate_and_normalize(raw, mapping, options)

    assert validation.valid is True
    assert validation.profile is not None
    profile = validation.profile.model_copy(update={"dataset_id": "fixture-complete", "session_id": "session-e2e"})
    dataset_store = DatasetStore(tmp_path / "datasets")
    reference = dataset_store.save("session-e2e", frame, profile)

    request = AnalysisRequest(
        dataset_id=reference.dataset_id,
        current_start=date(2024, 1, 1),
        current_end=date(2024, 12, 31),
        comparison="yoy",
        group_by=["category", "region"],
        confirmed_coverage=DateRange(start=profile.min_date, end=profile.max_date),
        anomaly_threshold=Decimal("0.30"),
        absolute_drop_threshold=Decimal("100.00"),
    )
    analysis_store = AnalysisStore(tmp_path / "analyses")
    result = run_business_report(
        "session-e2e",
        request,
        ["word", "pdf"],
        dataset_store=dataset_store,
        analysis_store=analysis_store,
        output_root=tmp_path / "reports",
    )

    assert result.stage_status["load"] == "completed"
    assert result.stage_status["analysis"] == "completed"
    assert result.stage_status["charts"] == "completed"
    assert result.stage_status["export"] == "completed"
    assert result.errors == []
    assert "narrative fallback used" in result.warnings
    assert len(result.artifacts) == 2

    report_dir = tmp_path / "reports" / "session-e2e" / result.analysis_id
    chart_files = list((report_dir / "charts").glob("*.png"))
    assert chart_files
    assert all(path.stat().st_size > 0 for path in chart_files)

    artifact_by_suffix = {Path(item.storage_key).suffix: item for item in result.artifacts}
    assert {".docx", ".pdf"} == set(artifact_by_suffix)
    for artifact in result.artifacts:
        verification = verify_report_artifact(artifact)
        assert verification.valid, verification.errors
        assert "核心指标" in verification.extracted_text
        assert "销售额" in verification.extracted_text

    stored = analysis_store.get("session-e2e", result.analysis_id)
    assert Decimal(stored["metrics"]["sales"]["value"]) == Decimal("1995.00")
    assert Decimal(stored["metrics"]["gross_profit"]["value"]) == Decimal("1092.00")
    assert Decimal(stored["comparisons"][0]["previous"]["value"]) == Decimal("1333.50")
    assert stored["comparisons"][0]["change"]["value"] is None
    assert stored["comparisons"][0]["completeness"] == "incomplete"
    assert "coverage" in stored["comparisons"][0]["change"]["reason"].lower()
    category_ranking = next(item for item in stored["rankings"] if item["dimension"] == "category")
    assert category_ranking["items"][0]["dimension"] == "运动户外"
    assert stored["evidence"]
    evidence_ids = {item["evidence_id"] for item in stored["evidence"]}
    assert any(item["kind"] == "metric" for item in stored["evidence"])
