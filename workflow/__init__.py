"""业务分析与报告导出的流程编排入口。"""

from .business_report import WorkflowResult, run_business_report

__all__ = ["WorkflowResult", "run_business_report"]
