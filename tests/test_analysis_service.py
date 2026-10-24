from datetime import date
from decimal import Decimal

import pandas as pd

from analytics.analysis_service import run_analysis
from models.analysis import AnalysisRequest
from models.sales import DatasetProfile


def test_run_analysis_orchestrates_shared_analysis_result():
    frame = pd.DataFrame([
        {"order_date": date(2024, 1, 15), "sales_amount": "100.00", "refund_amount": "0.00", "cost_amount": "40.00", "order_id": "A", "category": "A", "region": "North"},
        {"order_date": date(2024, 2, 15), "sales_amount": "150.00", "refund_amount": "10.00", "cost_amount": "60.00", "order_id": "B", "category": "A", "region": "North"},
    ])
    original = frame.copy(deep=True)
    request = AnalysisRequest(
        dataset_id="ds_test",
        current_start=date(2024, 2, 1),
        current_end=date(2024, 2, 29),
        comparison="mom",
        group_by=["category", "region"],
        confirmed_coverage={"start": date(2024, 1, 1), "end": date(2024, 2, 29)},
    )
    profile = DatasetProfile(
        dataset_id="ds_test",
        session_id="session_test",
        rows=2,
        columns=list(frame.columns),
        grain="order_line",
        currency="USD",
        min_date=date(2024, 1, 15),
        max_date=date(2024, 2, 15),
        available_metrics=["sales", "net_sales", "gross_profit", "gross_margin", "order_count"],
        unavailable_metrics={},
    )

    result = run_analysis(frame, request, profile)

    assert result.dataset_id == "ds_test"
    assert result.analysis_id
    assert result.metrics["net_sales"].value == Decimal("140.00")
    assert any(item.dimension == "sales" for item in result.comparisons)
    assert {item.dimension for item in result.rankings} == {"category", "region"}
    assert result.evidence
    pd.testing.assert_frame_equal(frame, original)
