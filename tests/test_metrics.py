from datetime import date
from decimal import Decimal

import pandas as pd

from analytics.metrics import calculate_metrics
from data_sources.mapper import map_columns
from data_sources.validator import validate_and_normalize
from models.sales import AnalysisAssumptions, ImportOptions, RawDataset


def _load(path, *, grain="order_line", assume_no_refunds=False):
    frame = pd.read_csv(path)
    options = ImportOptions(
        source_name=path.name,
        grain=grain,
        assume_no_refunds=assume_no_refunds,
    )
    normalized, validation = validate_and_normalize(
        RawDataset(frame, options),
        map_columns(frame, {}),
        options,
    )
    assert validation.valid, validation.errors
    return normalized


def test_calculate_complete_period_metrics(complete_sales_csv):
    frame = _load(complete_sales_csv)
    metrics = calculate_metrics(
        frame,
        date(2024, 1, 1),
        date(2024, 12, 31),
        "order_line",
        AnalysisAssumptions(
            confirmed_coverage={"start": date(2023, 1, 1), "end": date(2024, 12, 31)},
        ),
    )

    assert metrics["sales"].value == Decimal("1995.00")
    assert metrics["net_sales"].value == Decimal("1980.00")
    assert metrics["order_count"].value == Decimal("12")
    assert metrics["average_order_value"].value == Decimal("165.00")
    assert metrics["gross_profit"].value == Decimal("1092.00")
    assert metrics["gross_margin"].value == Decimal("0.5515")
    assert metrics["quantity"].value == Decimal("32")


def test_calculate_metrics_does_not_mutate_input(complete_sales_csv):
    frame = _load(complete_sales_csv)
    original = frame.copy(deep=True)

    calculate_metrics(
        frame,
        date(2024, 6, 1),
        date(2024, 6, 30),
        "order_line",
        AnalysisAssumptions(),
    )

    pd.testing.assert_frame_equal(frame, original)


def test_average_order_value_is_unavailable_when_net_sales_is_unavailable():
    frame = pd.DataFrame([
        {"order_date": "2024-01-01", "sales_amount": "100.00", "order_id": "o1"},
        {"order_date": "2024-01-02", "sales_amount": "50.00", "order_id": "o2"},
    ])

    metrics = calculate_metrics(
        frame,
        date(2024, 1, 1),
        date(2024, 1, 31),
        "order_line",
        AnalysisAssumptions(),
    )

    assert metrics["net_sales"].value is None
    assert metrics["average_order_value"].value is None
    assert "net_sales" in metrics["average_order_value"].reason


def test_all_null_optional_amount_columns_are_unavailable() -> None:
    frame = pd.DataFrame([
        {
            "order_date": "2024-01-01",
            "sales_amount": "100.00",
            "refund_amount": None,
            "cost_amount": None,
        }
    ])

    metrics = calculate_metrics(
        frame,
        date(2024, 1, 1),
        date(2024, 1, 31),
        "order_line",
        AnalysisAssumptions(),
    )

    assert metrics["net_sales"].value is None
    assert "refund" in (metrics["net_sales"].reason or "").lower()
    assert metrics["gross_profit"].value is None
    assert "cost" in (metrics["gross_profit"].reason or "").lower()
    assert metrics["gross_margin"].value is None
    assert "cost" in (metrics["gross_margin"].reason or "").lower()


def test_high_precision_amounts_are_not_rounded_during_metric_calculation():
    frame = pd.DataFrame([{
        "order_date": "2024-01-01",
        "sales_amount": Decimal("0.0007"),
        "refund_amount": Decimal("0.0002"),
        "cost_amount": Decimal("0.0001"),
        "order_id": "o1",
    }])
    metrics = calculate_metrics(
        frame, date(2024, 1, 1), date(2024, 1, 31), "order_line", AnalysisAssumptions(),
    )
    assert metrics["sales"].value == Decimal("0.0007")
    assert metrics["net_sales"].value == Decimal("0.0005")
    assert metrics["gross_profit"].value == Decimal("0.0004")
