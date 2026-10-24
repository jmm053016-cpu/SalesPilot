"""计算当前期间与基准期间之间的指标变化及其证据。"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

import pandas as pd

from models.analysis import ComparisonResult, MetricValue
from models.sales import AnalysisAssumptions, DateRange


def _period(df: pd.DataFrame, period: DateRange) -> pd.DataFrame:
    dates = pd.to_datetime(df["order_date"], errors="coerce").dt.date
    return df.loc[(dates >= period.start) & (dates <= period.end)].copy(deep=True)


def _sum_sales(frame: pd.DataFrame) -> Decimal:
    if "sales_amount" not in frame.columns:
        return Decimal("0.00")
    total = Decimal("0.00")
    for value in frame["sales_amount"].tolist():
        if value is not None and not pd.isna(value):
            total += Decimal(str(value))
    return total


def _previous_period(current: DateRange, comparison: Literal["mom", "yoy"]) -> DateRange:
    if comparison == "yoy":
        try:
            start = current.start.replace(year=current.start.year - 1)
            end = current.end.replace(year=current.end.year - 1)
        except ValueError:
            start = current.start.replace(year=current.start.year - 1, day=28)
            end = current.end.replace(year=current.end.year - 1, day=28)
        return DateRange(start=start, end=end)
    if current.start.day == 1 and current.end.day == monthrange(current.end.year, current.end.month)[1]:
        if current.start.month == 1:
            year, month = current.start.year - 1, 12
        else:
            year, month = current.start.year, current.start.month - 1
        return DateRange(start=date(year, month, 1), end=date(year, month, monthrange(year, month)[1]))
    days = (current.end - current.start).days + 1
    end = current.start - timedelta(days=1)
    return DateRange(start=end - timedelta(days=days - 1), end=end)


def compare_periods(
    df: pd.DataFrame,
    current: DateRange,
    comparison: Literal["mom", "yoy"],
    assumptions: AnalysisAssumptions,
) -> list[ComparisonResult]:
    if comparison not in {"mom", "yoy"}:
        raise ValueError("comparison must be 'mom' or 'yoy'")
    previous = _previous_period(current, comparison)
    current_value = _sum_sales(_period(df, current))
    previous_rows = _period(df, previous)
    has_history = not previous_rows.empty
    coverage = assumptions.confirmed_coverage
    completeness = "unknown"
    reason_parts: list[str] = []
    if coverage is None:
        reason_parts.append("coverage was not confirmed")
    elif (
        coverage.start <= current.start
        and coverage.end >= current.end
        and coverage.start <= previous.start
        and coverage.end >= previous.end
    ):
        completeness = "complete"
    else:
        completeness = "incomplete"
        reason_parts.append(
            "current or comparison period is outside confirmed coverage"
        )
    if not has_history:
        reason_parts.append(f"no history for {previous.start.isoformat()[:7]}")
    previous_value = previous_value = _sum_sales(previous_rows) if has_history or coverage is not None else Decimal("0.00")
    if not has_history:
        previous_metric = MetricValue(value=None, unit="currency", reason=reason_parts[-1])
        change = MetricValue(value=None, unit="ratio", reason=reason_parts[-1])
    else:
        previous_metric = MetricValue(value=previous_value, unit="currency")
        if completeness != "complete":
            reason = (
                "change is unavailable because comparison coverage is incomplete"
                if completeness == "incomplete"
                else "change is unavailable because coverage was not confirmed"
            )
            change = MetricValue(value=None, unit="ratio", reason=reason)
        elif previous_value == 0:
            change = MetricValue(value=None, unit="ratio", reason="change is unavailable because previous value is zero")
        else:
            change = MetricValue(value=((current_value - previous_value) / previous_value).quantize(Decimal("0.0000"), rounding=ROUND_HALF_UP), unit="ratio")
    return [ComparisonResult(
        dimension="sales",
        current=MetricValue(value=current_value, unit="currency"),
        previous=previous_metric,
        change=change,
        completeness=completeness,
        reason="; ".join(reason_parts) or None,
    )]
