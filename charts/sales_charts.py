"""依据分析结果生成销售趋势、构成和排名图表。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import matplotlib.pyplot as plt

from models.analysis import AnalysisResult, MetricValue
from models.report import ChartArtifact
from .chart_style import apply_style, save_figure


def _period_title(result: AnalysisResult) -> str:
    return f"{result.request.current_start.isoformat()} to {result.request.current_end.isoformat()}"


def _metric_value(value: MetricValue | None) -> float | None:
    if value is None or value.value is None:
        return None
    return float(value.value)


def _artifact(output_dir: Path, result: AnalysisResult, kind: str, title: str, evidence_ids: list[str]) -> ChartArtifact:
    path = output_dir / f"{result.analysis_id}-{kind}.png"
    return ChartArtifact(
        artifact_id=f"chart_{uuid4().hex}",
        kind=kind,
        path=path,
        mime_type="image/png",
        title=title,
        source_evidence_ids=evidence_ids,
    )


def _evidence_for(result: AnalysisResult, label: str | None = None) -> list[str]:
    return [item.evidence_id for item in result.evidence if label is None or item.label == label]


def _ranking_charts(result: AnalysisResult, output_dir: Path) -> list[ChartArtifact]:
    charts: list[ChartArtifact] = []
    for ranking in result.rankings:
        values = [(str(item.get("dimension")), _metric_value(item.get("value"))) for item in ranking.items]
        values = [(label, value) for label, value in values if value is not None]
        if not values:
            continue
        title = f"{ranking.dimension} {ranking.metric} ranking ({_period_title(result)})"
        artifact = _artifact(output_dir, result, f"{ranking.dimension}-ranking", title, _evidence_for(result, ranking.metric))
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.bar([label for label, _ in values], [value for _, value in values])
        ax.set_title(title)
        ax.set_ylabel(ranking.metric)
        fig.autofmt_xdate()
        save_figure(fig, artifact.path)
        charts.append(artifact)
    return charts


def _comparison_chart(result: AnalysisResult, output_dir: Path) -> ChartArtifact | None:
    values: list[tuple[str, float]] = []
    for item in result.comparisons:
        current = _metric_value(item.current)
        previous = _metric_value(item.previous)
        if current is not None:
            values.append((f"{item.dimension} current", current))
        if previous is not None:
            values.append((f"{item.dimension} previous", previous))
    if not values:
        return None
    title = f"Period comparison ({_period_title(result)})"
    artifact = _artifact(output_dir, result, "period-comparison", title, _evidence_for(result, "sales"))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar([label for label, _ in values], [value for _, value in values])
    ax.set_title(title)
    ax.set_ylabel("value")
    fig.autofmt_xdate()
    save_figure(fig, artifact.path)
    return artifact


def _anomaly_chart(result: AnalysisResult, output_dir: Path) -> ChartArtifact | None:
    if not result.anomalies:
        return None
    values = [(item.dimension, float(item.current_value)) for item in result.anomalies]
    title = f"Anomalies ({_period_title(result)})"
    artifact = _artifact(output_dir, result, "anomalies", title, [item.evidence_id for item in result.anomalies])
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar([label for label, _ in values], [value for _, value in values], color="#c44e52")
    ax.set_title(title)
    ax.set_ylabel("current value")
    fig.autofmt_xdate()
    save_figure(fig, artifact.path)
    return artifact


def _gross_profit_chart(result: AnalysisResult, output_dir: Path) -> ChartArtifact | None:
    metric = result.metrics.get("gross_profit")
    value = _metric_value(metric)
    if value is None:
        return None
    title = f"Gross profit ({_period_title(result)})"
    artifact = _artifact(output_dir, result, "gross-profit", title, _evidence_for(result, "gross_profit"))
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(["gross profit"], [value], color="#55a868")
    ax.set_title(title)
    ax.set_ylabel("currency")
    save_figure(fig, artifact.path)
    return artifact


def _trend_chart(result: AnalysisResult, output_dir: Path) -> ChartArtifact | None:
    points = [(item.period.start, item.value) for item in result.evidence if item.kind == "metric" and item.label == "sales" and item.period and item.value is not None]
    if len(points) < 2:
        return None
    points.sort(key=lambda item: item[0])
    title = f"Sales trend ({_period_title(result)})"
    artifact = _artifact(output_dir, result, "sales-trend", title, _evidence_for(result, "sales"))
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot([point[0].isoformat() for point in points], [float(point[1]) for point in points], marker="o")
    ax.set_title(title)
    ax.set_ylabel("sales")
    fig.autofmt_xdate()
    save_figure(fig, artifact.path)
    return artifact


def generate_charts(result: AnalysisResult, output_dir: Path) -> list[ChartArtifact]:
    """Generate only charts backed by non-empty structured analysis data."""
    apply_style()
    output_dir = Path(output_dir)
    charts = []
    trend = _trend_chart(result, output_dir)
    if trend:
        charts.append(trend)
    charts.extend(_ranking_charts(result, output_dir))
    comparison = _comparison_chart(result, output_dir)
    if comparison:
        charts.append(comparison)
    anomaly = _anomaly_chart(result, output_dir)
    if anomaly:
        charts.append(anomaly)
    gross_profit = _gross_profit_chart(result, output_dir)
    if gross_profit:
        charts.append(gross_profit)
    return charts
