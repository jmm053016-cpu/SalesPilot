from datetime import date
from decimal import Decimal

import pytest

from models.analysis import AnalysisRequest, AnalysisResult, Evidence, MetricValue
from models.report import ReportModel
from models.sales import DateRange
from reports.report_model import build_report_model


def _result():
    period = DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))
    request = AnalysisRequest(
        dataset_id="ds_report",
        current_start=period.start,
        current_end=period.end,
        comparison="none",
        group_by=[],
    )
    return AnalysisResult(
        analysis_id="analysis_report",
        dataset_id="ds_report",
        request=request,
        metrics={"sales": MetricValue(value=Decimal("100.00"), unit="currency")},
        evidence=[Evidence(evidence_id="ev_sales", kind="metric", label="sales", value=Decimal("100.00"), unit="currency", period=period)],
    )


def test_build_report_model_preserves_analysis_and_evidence():
    result = _result()

    report = build_report_model(result, narrative=None, charts=[])

    assert isinstance(report, ReportModel)
    assert report.analysis is not None
    assert report.analysis.analysis_id == result.analysis_id
    assert report.dataset_id == result.dataset_id
    assert report.period == DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))
    assert report.analysis.evidence[0].evidence_id == "ev_sales"


def test_report_model_rejects_unsupported_schema_version():
    with pytest.raises(ValueError, match="unsupported schema_version"):
        ReportModel(
            schema_version="9.9",
            report_id="report_bad",
            analysis_id="analysis_bad",
            dataset_id="ds_bad",
            period={"start": date(2024, 1, 1), "end": date(2024, 1, 31)},
        )
