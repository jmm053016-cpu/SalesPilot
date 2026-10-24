from datetime import date
from decimal import Decimal

import pandas as pd

from analytics.comparisons import compare_periods
from models.sales import AnalysisAssumptions, DateRange


def _frame(rows):
    return pd.DataFrame(rows)


def test_compare_month_over_month_uses_adjacent_calendar_periods():
    frame = _frame([
        {"order_date": date(2024, 1, 15), "sales_amount": "100.00"},
        {"order_date": date(2024, 2, 15), "sales_amount": "150.00"},
    ])

    results = compare_periods(
        frame,
        DateRange(start=date(2024, 2, 1), end=date(2024, 2, 29)),
        "mom",
        AnalysisAssumptions(confirmed_coverage=DateRange(start=date(2024, 1, 1), end=date(2024, 2, 29))),
    )

    sales = next(item for item in results if item.dimension == "sales")
    assert sales.current.value == Decimal("150.00")
    assert sales.previous.value == Decimal("100.00")
    assert sales.change.value == Decimal("0.5000")
    assert sales.completeness == "complete"


def test_compare_year_over_year_crosses_year_boundary_without_fallback():
    frame = _frame([
        {"order_date": date(2023, 12, 15), "sales_amount": "90.00"},
        {"order_date": date(2024, 1, 15), "sales_amount": "120.00"},
    ])

    results = compare_periods(
        frame,
        DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31)),
        "yoy",
        AnalysisAssumptions(confirmed_coverage=DateRange(start=date(2023, 1, 1), end=date(2024, 1, 31))),
    )

    sales = next(item for item in results if item.dimension == "sales")
    assert sales.previous.value is None
    assert "2023-01" in sales.reason


def test_compare_zero_baseline_is_unavailable_not_infinite():
    frame = _frame([
        {"order_date": date(2024, 1, 15), "sales_amount": "0.00"},
        {"order_date": date(2024, 2, 15), "sales_amount": "150.00"},
    ])

    results = compare_periods(
        frame,
        DateRange(start=date(2024, 2, 1), end=date(2024, 2, 29)),
        "mom",
        AnalysisAssumptions(confirmed_coverage=DateRange(start=date(2024, 1, 1), end=date(2024, 2, 29))),
    )

    sales = next(item for item in results if item.dimension == "sales")
    assert sales.current.value == Decimal("150.00")
    assert sales.previous.value == Decimal("0.00")
    assert sales.change.value is None
    assert "zero" in sales.change.reason.lower()


def test_compare_requires_history_and_does_not_use_another_month():
    frame = _frame([
        {"order_date": date(2024, 1, 15), "sales_amount": "100.00"},
        {"order_date": date(2024, 3, 15), "sales_amount": "300.00"},
    ])

    results = compare_periods(
        frame,
        DateRange(start=date(2024, 3, 1), end=date(2024, 3, 31)),
        "mom",
        AnalysisAssumptions(confirmed_coverage=DateRange(start=date(2024, 1, 1), end=date(2024, 3, 31))),
    )

    sales = next(item for item in results if item.dimension == "sales")
    assert sales.previous.value is None
    assert "2024-02" in sales.reason


def test_compare_marks_unconfirmed_coverage_unknown():
    frame = _frame([
        {"order_date": date(2024, 1, 15), "sales_amount": "100.00"},
        {"order_date": date(2024, 2, 15), "sales_amount": "150.00"},
    ])

    results = compare_periods(
        frame,
        DateRange(start=date(2024, 2, 1), end=date(2024, 2, 15)),
        "mom",
        AnalysisAssumptions(),
    )

    sales = next(item for item in results if item.dimension == "sales")
    assert sales.completeness == "unknown"
    assert "coverage" in sales.reason.lower()


def test_compare_does_not_calculate_growth_for_incomplete_coverage():
    frame = _frame([
        {"order_date": date(2024, 1, 15), "sales_amount": "100.00"},
        {"order_date": date(2024, 2, 15), "sales_amount": "150.00"},
    ])

    results = compare_periods(
        frame,
        DateRange(start=date(2024, 2, 1), end=date(2024, 2, 29)),
        "mom",
        AnalysisAssumptions(
            confirmed_coverage=DateRange(start=date(2024, 1, 15), end=date(2024, 2, 29))
        ),
    )

    sales = next(item for item in results if item.dimension == "sales")
    assert sales.completeness == "incomplete"
    assert sales.change.value is None
    assert "coverage" in (sales.change.reason or "").lower()


def test_compare_does_not_calculate_growth_when_current_period_is_incomplete():
    frame = _frame([
        {"order_date": date(2024, 1, 15), "sales_amount": "100.00"},
        {"order_date": date(2024, 2, 15), "sales_amount": "150.00"},
    ])

    results = compare_periods(
        frame,
        DateRange(start=date(2024, 2, 1), end=date(2024, 2, 29)),
        "mom",
        AnalysisAssumptions(
            confirmed_coverage=DateRange(start=date(2024, 1, 1), end=date(2024, 2, 15))
        ),
    )

    sales = next(item for item in results if item.dimension == "sales")
    assert sales.completeness == "incomplete"
    assert sales.change.value is None
    assert "coverage" in (sales.change.reason or "").lower()


def test_compare_does_not_calculate_growth_when_coverage_is_unknown():
    frame = _frame([
        {"order_date": date(2024, 1, 20), "sales_amount": "100.00"},
        {"order_date": date(2024, 2, 10), "sales_amount": "150.00"},
    ])

    results = compare_periods(
        frame,
        DateRange(start=date(2024, 2, 1), end=date(2024, 2, 15)),
        "mom",
        AnalysisAssumptions(),
    )

    sales = next(item for item in results if item.dimension == "sales")
    assert sales.completeness == "unknown"
    assert sales.previous.value == Decimal("100.00")
    assert sales.change.value is None
    assert "coverage" in (sales.change.reason or "").lower()
