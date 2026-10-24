from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from analytics.anomaly import detect_anomalies
from models.sales import AnomalyConfig, DateRange


def _daily_rows(values, end_date=date(2024, 2, 29)):
    start_date = end_date - timedelta(days=len(values) - 1)
    return [
        {"order_date": start_date + timedelta(days=index), "sales_amount": str(value)}
        for index, value in enumerate(values)
    ]


def test_daily_anomaly_uses_prior_28_days_and_excludes_current_day():
    # Fourteen valid baseline dates within the 28 calendar days before current day.
    baseline = [90 if index % 2 == 0 else 110 for index in range(14)]
    rows = _daily_rows(baseline, date(2024, 2, 28))
    rows.append({"order_date": date(2024, 2, 29), "sales_amount": "120"})

    anomalies = detect_anomalies(
        pd.DataFrame(rows),
        DateRange(start=date(2024, 2, 29), end=date(2024, 2, 29)),
        AnomalyConfig(),
    )

    daily = next(item for item in anomalies if item.dimension == "daily_sales")
    assert daily.current_value == Decimal("120")
    assert daily.baseline_value == Decimal("100")
    assert daily.severity == "medium"
    assert daily.algorithm == "z_score"
    assert daily.evidence_id


def test_daily_anomaly_z_score_three_is_high():
    baseline = [90 if index % 2 == 0 else 110 for index in range(14)]
    rows = _daily_rows(baseline, date(2024, 2, 28))
    rows.append({"order_date": date(2024, 2, 29), "sales_amount": "130"})

    anomalies = detect_anomalies(
        pd.DataFrame(rows),
        DateRange(start=date(2024, 2, 29), end=date(2024, 2, 29)),
        AnomalyConfig(),
    )

    daily = next(item for item in anomalies if item.dimension == "daily_sales")
    assert daily.severity == "high"
    assert daily.threshold == Decimal("3")


def test_zero_standard_deviation_does_not_emit_infinite_statistical_anomaly():
    rows = _daily_rows([100] * 14, date(2024, 2, 28))
    rows.append({"order_date": date(2024, 2, 29), "sales_amount": "200"})

    anomalies = detect_anomalies(
        pd.DataFrame(rows),
        DateRange(start=date(2024, 2, 29), end=date(2024, 2, 29)),
        AnomalyConfig(),
    )

    assert not any(item.dimension == "daily_sales" for item in anomalies)


def test_positive_value_against_confirmed_all_zero_baseline_is_cold_start():
    rows = _daily_rows([0] * 14, date(2024, 2, 28))
    rows.append({"order_date": date(2024, 2, 29), "sales_amount": "25"})

    anomalies = detect_anomalies(
        pd.DataFrame(rows),
        DateRange(start=date(2024, 2, 29), end=date(2024, 2, 29)),
        AnomalyConfig(),
    )

    daily = next(item for item in anomalies if item.dimension == "daily_sales")
    assert daily.severity == "cold_start"
    assert "statistical" in daily.reason.lower()


def test_daily_detection_is_disabled_with_fewer_than_14_baseline_dates():
    rows = _daily_rows([90, 110] * 6 + [100], date(2024, 2, 28))
    rows.append({"order_date": date(2024, 2, 29), "sales_amount": "300"})

    anomalies = detect_anomalies(
        pd.DataFrame(rows),
        DateRange(start=date(2024, 2, 29), end=date(2024, 2, 29)),
        AnomalyConfig(min_history=14),
    )

    assert not any(item.dimension == "daily_sales" for item in anomalies)


@pytest.mark.parametrize("dimension", ["category", "region"])
def test_dimension_decline_requires_both_relative_and_absolute_thresholds(dimension):
    rows = []
    for offset in range(60):
        day = date(2024, 1, 1) + timedelta(days=offset)
        value = "100" if offset < 30 else "60"
        rows.append({"order_date": day, "sales_amount": value, dimension: "A"})

    anomalies = detect_anomalies(
        pd.DataFrame(rows),
        DateRange(start=date(2024, 1, 31), end=date(2024, 3, 1)),
        AnomalyConfig(relative_drop=Decimal("0.30"), absolute_drop=Decimal("1000")),
    )

    decline = next(item for item in anomalies if item.dimension == dimension and item.current_value == Decimal("1800"))
    assert decline.baseline_value == Decimal("3000")
    assert decline.severity in {"medium", "high"}
    assert "relative" in decline.reason or "absolute" in decline.reason
