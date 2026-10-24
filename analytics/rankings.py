"""按业务维度聚合并排序销售表现，生成可追溯排名结果。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd

from models.analysis import RankingResult, MetricValue
from models.sales import DateRange


def rank_dimension(df: pd.DataFrame, period: DateRange, dimension: str, metric: str, top_n: int = 10) -> RankingResult:
    if top_n < 1:
        raise ValueError("top_n must be positive")
    if dimension not in df.columns:
        return RankingResult(dimension=dimension, metric=metric, period=period, items=[])
    dates = pd.to_datetime(df["order_date"], errors="coerce").dt.date
    frame = df.loc[(dates >= period.start) & (dates <= period.end)].copy(deep=True)
    value_columns = {"sales": "sales_amount", "quantity": "quantity"}
    if metric == "net_sales":
        required = {"sales_amount", "refund_amount"}
        if not required <= set(frame.columns):
            return RankingResult(dimension=dimension, metric=metric, period=period, items=[])
        if not frame["refund_amount"].notna().any():
            return RankingResult(dimension=dimension, metric=metric, period=period, items=[])
        value_column = "net_sales"
        frame[value_column] = [
            (Decimal(str(sales)) if sales is not None and not pd.isna(sales) else Decimal(0))
            - (Decimal(str(refund)) if refund is not None and not pd.isna(refund) else Decimal(0))
            for sales, refund in zip(frame["sales_amount"], frame["refund_amount"])
        ]
    elif metric == "gross_profit":
        required = {"sales_amount", "refund_amount", "cost_amount"}
        if not required <= set(frame.columns):
            return RankingResult(dimension=dimension, metric=metric, period=period, items=[])
        frame["cost_amount"] = pd.to_numeric(frame["cost_amount"], errors="coerce")
        if not frame["refund_amount"].notna().any() or not frame["cost_amount"].notna().any():
            return RankingResult(dimension=dimension, metric=metric, period=period, items=[])
        value_column = "gross_profit"
        frame[value_column] = [
            (Decimal(str(sales)) if sales is not None and not pd.isna(sales) else Decimal(0))
            - (Decimal(str(refund)) if refund is not None and not pd.isna(refund) else Decimal(0))
            - (Decimal(str(cost)) if cost is not None and not pd.isna(cost) else Decimal(0))
            for sales, refund, cost in zip(frame["sales_amount"], frame["refund_amount"], frame["cost_amount"])
        ]
    else:
        value_column = value_columns.get(metric, "")
        if not value_column or value_column not in frame.columns:
            return RankingResult(dimension=dimension, metric=metric, period=period, items=[])
    rows: list[dict[str, Any]] = []
    for key, group in frame.groupby(dimension, dropna=False, sort=False):
        total = Decimal("0")
        for value in group[value_column].tolist():
            if value is not None and not pd.isna(value):
                total += Decimal(str(value))
        rows.append({"dimension": "(unknown)" if pd.isna(key) else str(key), "value": MetricValue(value=total, unit="units" if metric == "quantity" else "currency")})
    rows.sort(key=lambda item: (-item["value"].value, item["dimension"]))
    return RankingResult(dimension=dimension, metric=metric, period=period, items=rows[:top_n])
