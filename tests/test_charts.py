from datetime import date
from decimal import Decimal

import matplotlib
import pytest

import charts  # noqa: F401  导入即应固定后端
from charts.sales_charts import generate_charts
from models.analysis import AnalysisRequest, AnalysisResult, Evidence, MetricValue, RankingResult
from models.sales import DateRange


def test_chart_layer_forces_headless_backend():
    """图表只保存 PNG，不应依赖环境默认的交互式后端（如 TkAgg）。"""
    assert matplotlib.get_backend().lower() == "agg"


def _result(*, with_data=True):
    period = DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))
    request = AnalysisRequest(
        dataset_id="ds_chart",
        current_start=period.start,
        current_end=period.end,
        comparison="none",
        group_by=["category", "region"],
    )
    metrics = {
        "sales": MetricValue(value=Decimal("100.00"), unit="currency"),
    }
    rankings = [
        RankingResult(
            dimension="category",
            metric="sales",
            period=period,
            items=[{"dimension": "A", "value": MetricValue(value=Decimal("100.00"), unit="currency")}],
        ),
    ] if with_data else []
    return AnalysisResult(
        analysis_id="analysis_chart",
        dataset_id="ds_chart",
        request=request,
        metrics=metrics,
        rankings=rankings,
        evidence=[Evidence(evidence_id="ev_sales", kind="metric", label="sales", value=Decimal("100.00"), unit="currency", period=period)],
    )


def test_generate_charts_consumes_analysis_result_and_preserves_period(tmp_path):
    result = _result()

    charts = generate_charts(result, tmp_path)

    assert charts
    assert all(chart.path.exists() for chart in charts)
    assert all(chart.source_evidence_ids for chart in charts)
    assert all(result.request.current_start.isoformat() in chart.title or chart.kind for chart in charts)


def test_generate_charts_does_not_create_empty_placeholder_charts(tmp_path):
    result = _result(with_data=False)

    charts = generate_charts(result, tmp_path)

    assert charts == []


def test_generate_charts_reports_font_configuration_failure(tmp_path, monkeypatch):
    result = _result()

    def fail_font_setup():
        raise RuntimeError("Chinese font is unavailable")

    monkeypatch.setattr("charts.chart_style.configure_chinese_font", fail_font_setup)

    with pytest.raises(RuntimeError, match="Chinese font"):
        generate_charts(result, tmp_path)
