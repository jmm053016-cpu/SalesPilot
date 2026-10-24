"""将标准化销售数据转换为可复用的确定性分析结果。"""

from __future__ import annotations

from datetime import date
import uuid

import pandas as pd

from analytics.anomaly import detect_anomalies
from analytics.comparisons import compare_periods
from analytics.metrics import calculate_metrics
from analytics.rankings import rank_dimension
from models.analysis import AnalysisRequest, AnalysisResult, Evidence
from models.sales import AnalysisAssumptions, AnomalyConfig, DatasetProfile, DateRange


class AnalysisServiceError(RuntimeError):
    """Stable failure raised when deterministic analysis cannot be completed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _date_range(request: AnalysisRequest) -> DateRange:
    return DateRange(start=request.current_start, end=request.current_end)


def _assumptions(request: AnalysisRequest) -> AnalysisAssumptions:
    return AnalysisAssumptions(
        confirmed_coverage=request.confirmed_coverage,
        as_of_date=request.as_of_date,
    )


def _evidence(result: AnalysisResult) -> list[Evidence]:
    evidence: list[Evidence] = []
    period = DateRange(start=result.request.current_start, end=result.request.current_end)
    for name, metric in result.metrics.items():
        evidence.append(Evidence(
            evidence_id=f"{result.analysis_id}:metric:{name}",
            kind="metric",
            label=name,
            value=metric.value,
            unit=metric.unit,
            period=period,
        ))
    for anomaly in result.anomalies:
        evidence.append(Evidence(
            evidence_id=anomaly.evidence_id,
            kind="anomaly",
            label=anomaly.dimension,
            value=anomaly.current_value,
            unit="currency",
            period=anomaly.period,
        ))
    return evidence


def run_analysis(
    dataset: pd.DataFrame,
    request: AnalysisRequest,
    profile: DatasetProfile,
) -> AnalysisResult:
    """Run the deterministic analysis pipeline without mutating ``dataset``."""
    if request.dataset_id != profile.dataset_id:
        raise AnalysisServiceError("unauthorized_dataset", "request dataset_id does not match dataset profile")
    if not isinstance(dataset, pd.DataFrame):
        raise AnalysisServiceError("invalid_data", "dataset must be a pandas DataFrame")
    required = {"order_date", "sales_amount"}
    missing = sorted(required.difference(dataset.columns))
    if missing:
        raise AnalysisServiceError("invalid_schema", f"dataset is missing required columns: {', '.join(missing)}")

    period = _date_range(request)
    assumptions = _assumptions(request)
    analysis_id = f"analysis_{uuid.uuid4().hex}"
    try:
        metrics = calculate_metrics(dataset, period.start, period.end, profile.grain, assumptions)
        comparisons = [] if request.comparison == "none" else compare_periods(dataset, period, request.comparison, assumptions)
        rankings = [
            rank_dimension(dataset, period, dimension, "sales")
            for dimension in request.group_by
            if dimension in dataset.columns
        ]
        anomaly_config = AnomalyConfig(
            relative_drop=request.anomaly_threshold,
            absolute_drop=request.absolute_drop_threshold,
        )
        anomalies = detect_anomalies(dataset, period, anomaly_config)
        result = AnalysisResult(
            analysis_id=analysis_id,
            dataset_id=request.dataset_id,
            request=request,
            metrics=metrics,
            comparisons=comparisons,
            rankings=rankings,
            anomalies=anomalies,
            evidence=[],
        )
        return result.model_copy(update={"evidence": _evidence(result)})
    except AnalysisServiceError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisServiceError("invalid_data", str(exc)) from exc
    except Exception as exc:
        raise AnalysisServiceError("analysis_failed", str(exc)) from exc
