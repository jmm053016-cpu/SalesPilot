"""按统一口径计算销售、退款、订单与利润类指标。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd

from models.analysis import MetricValue
from models.sales import AnalysisAssumptions


def _money(value: Any) -> Decimal:
    if value is None or pd.isna(value):
        return Decimal("0.00")
    return Decimal(str(value))


def _sum_decimal(series: pd.Series) -> Decimal:
    total = Decimal("0.00")
    for value in series.tolist():
        total += _money(value)
    return total


def _available(value: Decimal, unit: str) -> MetricValue:
    return MetricValue(value=value, unit=unit)


def _unavailable(unit: str, reason: str) -> MetricValue:
    return MetricValue(value=None, unit=unit, reason=reason)


def _period_frame(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    dates = pd.to_datetime(df["order_date"], errors="coerce").dt.date
    return df.loc[(dates >= start) & (dates <= end)].copy(deep=True)


def calculate_metrics(
    df: pd.DataFrame,
    start: date,
    end: date,
    grain: str,
    assumptions: AnalysisAssumptions,
) -> dict[str, MetricValue]:
    """Calculate deterministic sales metrics for an inclusive date range.

    The input frame is never modified. Missing capabilities are represented by
    MetricValue(value=None, reason=...).
    """
    period = _period_frame(df, start, end)
    sales = _sum_decimal(period["sales_amount"]) if "sales_amount" in period else Decimal("0.00")
    metrics: dict[str, MetricValue] = {
        "sales": _available(sales, "currency"),
    }

    has_refund_values = "refund_amount" in period.columns and period["refund_amount"].notna().any()
    if has_refund_values:
        refunds = _sum_decimal(period["refund_amount"])
        net_sales = (sales - refunds)
        metrics["net_sales"] = _available(net_sales, "currency")
    elif assumptions.assume_no_refunds:
        metrics["net_sales"] = _available(sales, "currency")
    else:
        refund_reason = (
            "refund_amount is empty and no zero-refund assumption was confirmed"
            if "refund_amount" in period.columns
            else "refund_amount is missing and no zero-refund assumption was confirmed"
        )
        metrics["net_sales"] = _unavailable("currency", refund_reason)

    if "order_id" in period.columns and grain != "aggregate":
        order_count = period["order_id"].dropna().astype(str).nunique()
        metrics["order_count"] = _available(Decimal(order_count), "orders")
        if not order_count:
            metrics["average_order_value"] = _unavailable("currency/order", "period contains no orders")
        elif metrics["net_sales"].value is None:
            metrics["average_order_value"] = _unavailable("currency/order", "net_sales is unavailable")
        else:
            metrics["average_order_value"] = _available(
                (metrics["net_sales"].value / Decimal(order_count)),
                "currency/order",
            )
    else:
        reason = "stable order_id is unavailable or dataset grain is aggregate"
        metrics["order_count"] = _unavailable("orders", reason)
        metrics["average_order_value"] = _unavailable("currency/order", reason)

    has_cost_values = "cost_amount" in period.columns and period["cost_amount"].notna().any()
    if has_cost_values:
        cost = _sum_decimal(period["cost_amount"])
        net_value = metrics["net_sales"].value
        if net_value is None:
            metrics["gross_profit"] = _unavailable("currency", "net_sales is unavailable")
            metrics["gross_margin"] = _unavailable("ratio", "net_sales is unavailable")
        else:
            gross_profit = (net_value - cost)
            metrics["gross_profit"] = _available(gross_profit, "currency")
            if net_value == 0:
                metrics["gross_margin"] = _unavailable("ratio", "net_sales is zero")
            else:
                margin = (gross_profit / net_value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                metrics["gross_margin"] = _available(margin, "ratio")
    else:
        cost_reason = "cost_amount is empty" if "cost_amount" in period.columns else "cost_amount is missing"
        metrics["gross_profit"] = _unavailable("currency", cost_reason)
        metrics["gross_margin"] = _unavailable("ratio", cost_reason)

    if "quantity" in period.columns:
        quantity = Decimal("0")
        for value in period["quantity"].tolist():
            if value is not None and not pd.isna(value):
                quantity += Decimal(str(value))
        metrics["quantity"] = _available(quantity, "units")
    else:
        metrics["quantity"] = _unavailable("units", "quantity is missing")

    return metrics
