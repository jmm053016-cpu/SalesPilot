"""基于明确阈值与业务口径识别销售数据中的异常信号。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import hashlib

import pandas as pd

from models.analysis import AnomalyResult
from models.sales import AnomalyConfig, DateRange


def _money(value) -> Decimal:
    if value is None or pd.isna(value):
        return Decimal("0.00")
    return Decimal(str(value))


def _period(df: pd.DataFrame, period: DateRange) -> pd.DataFrame:
    dates = pd.to_datetime(df["order_date"], errors="coerce").dt.date
    return df.loc[(dates >= period.start) & (dates <= period.end)].copy(deep=True)


def _sum(frame: pd.DataFrame) -> Decimal:
    return sum((_money(v) for v in frame["sales_amount"].tolist()), Decimal("0"))


def _id(dimension: str, period: DateRange) -> tuple[str, str]:
    raw = f"{dimension}:{period.start.isoformat()}:{period.end.isoformat()}".encode()
    token = hashlib.sha1(raw).hexdigest()[:12]
    return f"anomaly-{token}", f"evidence-{token}"


def _result(dimension: str, period: DateRange, current: Decimal, baseline: Decimal | None, algorithm: str, threshold: Decimal, severity: str, reason: str | None = None) -> AnomalyResult:
    anomaly_id, evidence_id = _id(dimension, period)
    return AnomalyResult(anomaly_id=anomaly_id, evidence_id=evidence_id, dimension=dimension, period=period, current_value=current, baseline_value=baseline, algorithm=algorithm, threshold=threshold, severity=severity, reason=reason)


def detect_anomalies(df: pd.DataFrame, period: DateRange, config: AnomalyConfig) -> list[AnomalyResult]:
    if "order_date" not in df.columns or "sales_amount" not in df.columns:
        return []
    results: list[AnomalyResult] = []
    current = _period(df, period)
    dates = pd.to_datetime(df["order_date"], errors="coerce").dt.date
    baseline_start = period.start - timedelta(days=config.window_days)
    baseline_end = period.start - timedelta(days=1)
    baseline_frame = df.loc[(dates >= baseline_start) & (dates <= baseline_end)].copy(deep=True)
    daily = baseline_frame.assign(_date=pd.to_datetime(baseline_frame["order_date"]).dt.date).groupby("_date")["sales_amount"].apply(lambda s: sum((_money(v) for v in s), Decimal("0.00")))
    current_daily = current.assign(_date=pd.to_datetime(current["order_date"]).dt.date).groupby("_date")["sales_amount"].apply(lambda s: sum((_money(v) for v in s), Decimal("0.00")))
    for day, current_value in current_daily.items():
        if len(daily) < config.min_history:
            continue
        baseline_value = (sum(daily, Decimal("0.00")) / Decimal(len(daily)))
        variance = sum(((value - baseline_value) ** 2 for value in daily), Decimal("0")) / Decimal(len(daily))
        std = variance.sqrt() if variance > 0 else Decimal("0")
        if baseline_value == 0 and current_value > 0:
            results.append(_result("daily_sales", DateRange(start=day, end=day), current_value, baseline_value, "z_score", config.medium_z, "cold_start", "statistical baseline is zero"))
        elif std != 0:
            z = abs(current_value - baseline_value) / std
            if z >= config.high_z:
                results.append(_result("daily_sales", DateRange(start=day, end=day), current_value, baseline_value, "z_score", config.high_z, "high"))
            elif z >= config.medium_z:
                results.append(_result("daily_sales", DateRange(start=day, end=day), current_value, baseline_value, "z_score", config.medium_z, "medium"))
    length = (period.end - period.start).days + 1
    comparison_start = period.start - timedelta(days=length)
    comparison_end = period.start - timedelta(days=1)
    previous = DateRange(start=comparison_start, end=comparison_end)
    for dimension in ("category", "region"):
        if dimension not in current.columns:
            continue
        for key, group in current.groupby(dimension, dropna=False):
            current_value = _sum(group)
            previous_group = df.loc[(dates >= previous.start) & (dates <= previous.end) & (df[dimension] == key)]
            baseline_value = _sum(previous_group)
            if baseline_value <= 0:
                continue
            relative = (baseline_value - current_value) / baseline_value
            absolute = baseline_value - current_value
            if relative >= config.relative_drop and absolute >= config.absolute_drop:
                results.append(_result(dimension, period, current_value, baseline_value, "dual_threshold", config.relative_drop, "high" if relative >= Decimal("0.5") else "medium", f"relative drop {relative:.4f}; absolute drop {absolute:.2f}"))
    return results
