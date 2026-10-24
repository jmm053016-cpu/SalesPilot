"""将分析结果、叙述和图表组装为统一报告模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from models.analysis import AnalysisResult
from models.report import ChartArtifact, NarrativeResult, ReportMetadata, ReportModel


def _warnings(result: AnalysisResult) -> list[str]:
    warnings: list[str] = []
    for name, metric in result.metrics.items():
        if metric.value is None and metric.reason:
            warnings.append(f"{name}: {metric.reason}")
    for comparison in result.comparisons:
        if comparison.reason:
            warnings.append(f"comparison {comparison.dimension}: {comparison.reason}")
    return warnings


def build_report_model(
    result: AnalysisResult,
    narrative: NarrativeResult | None,
    charts: list[ChartArtifact],
) -> ReportModel:
    """Build the shared structured report consumed by Word, PDF, and UI renderers."""
    period = result.request.model_dump(include={"current_start", "current_end"})
    metadata = ReportMetadata(
        title=f"Sales analysis {result.request.current_start.isoformat()} to {result.request.current_end.isoformat()}",
        generated_at=datetime.now(timezone.utc).isoformat(),
        warnings=_warnings(result),
    )
    return ReportModel(
        report_id=f"report_{uuid4().hex}",
        analysis_id=result.analysis_id,
        dataset_id=result.dataset_id,
        period={"start": period["current_start"], "end": period["current_end"]},
        analysis=result,
        narrative=narrative,
        charts=list(charts),
        metadata=metadata,
    )
