"""确定性销售分析服务及其对外入口。"""

from .analysis_service import AnalysisServiceError, run_analysis
from .anomaly import detect_anomalies
from .comparisons import compare_periods
from .metrics import calculate_metrics
from .rankings import rank_dimension

__all__ = [
    "AnalysisServiceError",
    "calculate_metrics",
    "compare_periods",
    "detect_anomalies",
    "rank_dimension",
    "run_analysis",
]
