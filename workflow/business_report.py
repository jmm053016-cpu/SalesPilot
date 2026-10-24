"""编排分析、图表、叙述及报告导出，并记录各阶段状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Literal

from analytics.analysis_service import AnalysisServiceError, run_analysis
from charts import generate_charts
from models.analysis import AnalysisRequest, AnalysisResult
from models.report import ArtifactRef, ReportModel
from reports import pdf_report, word_report
from reports.narrative import generate_narrative
from reports.report_model import build_report_model
from storage.analyses import AnalysisStore
from storage.artifacts import ArtifactStore
from storage.datasets import DatasetStore, UnauthorizedDatasetError
from storage.profiles import load_dataset_profile
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class WorkflowResult:
    analysis_id: str | None = None
    stage_status: dict[str, str] = field(default_factory=dict)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # 交付给前端的确定性产物：分析成功即有 analysis，报告建模成功即有 report。
    # 数值仍以 analysis 为准，report 只承载解读、图表与产物引用。
    analysis: AnalysisResult | None = None
    report: ReportModel | None = None


def run_business_report(
    session_id: str,
    request: AnalysisRequest,
    formats: list[Literal["word", "pdf"]],
    *,
    dataset_store: DatasetStore | None = None,
    analysis_store: AnalysisStore | None = None,
    artifact_store: ArtifactStore | None = None,
    output_root: Path | str = ".runtime/reports",
    model=None,
    existing_analysis: AnalysisResult | None = None,
) -> WorkflowResult:
    dataset_store = dataset_store or DatasetStore()
    analysis_store = analysis_store or AnalysisStore()
    artifact_store = artifact_store or ArtifactStore()
    result = WorkflowResult()
    workflow_started = perf_counter()
    logger.info(
        "report.workflow.started | 报告分析流程开始 | 数据集ID=%s | 导出格式=%s | 是否复用已有分析=%s | 分组数量=%d",
        request.dataset_id,
        ",".join(formats) or "无",
        existing_analysis is not None,
        len(request.group_by),
    )
    stage_started = perf_counter()
    try:
        dataset = dataset_store.load(session_id, request.dataset_id)
        profile = load_dataset_profile(dataset_store, session_id, request.dataset_id)
        result.stage_status["load"] = "completed"
        logger.info("dataset.load.completed | 数据集加载完成 | 数据集ID=%s | 行数=%d | 列数=%d | 耗时=%d毫秒", request.dataset_id, len(dataset), len(dataset.columns), int((perf_counter() - stage_started) * 1000))
    except Exception as exc:
        result.stage_status["load"] = "failed"
        result.errors.append(f"unauthorized_dataset: {exc}")
        logger.warning(
            "dataset.load.failed | 数据集加载失败 | 数据集ID=%s | 异常类型=%s | 耗时=%d毫秒",
            request.dataset_id,
            type(exc).__name__,
            int((perf_counter() - stage_started) * 1000),
        )
        return result
    stage_started = perf_counter()
    logger.info("analysis.run.started | 确定性分析开始 | 数据集ID=%s | 使用已有分析=%s", request.dataset_id, existing_analysis is not None)
    try:
        if existing_analysis is None:
            analysis = run_analysis(dataset, request, profile)
            analysis_store.save(session_id, analysis.analysis_id, analysis)
        else:
            if existing_analysis.dataset_id != request.dataset_id or existing_analysis.request != request:
                raise AnalysisServiceError("invalid_analysis", "stored analysis does not match the export request")
            analysis = existing_analysis
        result.analysis_id = analysis.analysis_id
        result.analysis = analysis
        result.stage_status["analysis"] = "completed"
        logger.info(
            "analysis.run.completed | 确定性分析完成 | 数据集ID=%s | 分析ID=%s | 指标数量=%d | 证据数量=%d | 耗时=%d毫秒",
            request.dataset_id,
            analysis.analysis_id,
            len(analysis.metrics),
            len(analysis.evidence),
            int((perf_counter() - stage_started) * 1000),
        )
    except AnalysisServiceError as exc:
        result.stage_status["analysis"] = "failed"
        result.errors.append(f"{exc.code}: {exc.message}")
        logger.warning(
            "analysis.run.failed | 确定性分析失败 | 数据集ID=%s | 错误代码=%s | 耗时=%d毫秒",
            request.dataset_id,
            exc.code,
            int((perf_counter() - stage_started) * 1000),
        )
        return result
    chart_dir = Path(output_root) / session_id / analysis.analysis_id / "charts"
    stage_started = perf_counter()
    logger.info("charts.generate.started | 图表生成开始 | 分析ID=%s", analysis.analysis_id)
    try:
        charts = generate_charts(analysis, chart_dir)
        result.stage_status["charts"] = "completed"
        logger.info("charts.generate.completed | 图表生成完成 | 分析ID=%s | 图表数量=%d | 耗时=%d毫秒", analysis.analysis_id, len(charts), int((perf_counter() - stage_started) * 1000))
    except Exception as exc:
        charts = []
        result.stage_status["charts"] = "failed"
        result.warnings.append(f"charts: {exc}")
        logger.warning(
            "charts.generate.failed | 图表生成失败 | 分析ID=%s | 异常类型=%s | 耗时=%d毫秒",
            analysis.analysis_id,
            type(exc).__name__,
            int((perf_counter() - stage_started) * 1000),
        )
    stage_started = perf_counter()
    logger.info("narrative.generation.started | 模型解读生成开始 | 分析ID=%s", analysis.analysis_id)
    narrative = generate_narrative(analysis, model)
    logger.info(
        "narrative.generation.completed | 模型解读生成完成 | 分析ID=%s | 状态=%s | 观察数量=%d | 建议数量=%d | 耗时=%d毫秒",
        analysis.analysis_id,
        narrative.status,
        len(narrative.observations),
        len(narrative.recommendations),
        int((perf_counter() - stage_started) * 1000),
    )
    if narrative.status == "fallback":
        result.warnings.append("narrative fallback used")
    report = build_report_model(analysis, narrative, charts)
    report_dir = Path(output_root) / session_id / analysis.analysis_id / "reports"
    export_errors = []
    export_started = perf_counter()
    logger.info(
        "report.export.started | 报告导出开始 | 分析ID=%s | 请求格式数量=%d | 导出格式=%s",
        analysis.analysis_id,
        len(formats),
        ",".join(formats) or "无",
    )
    for format_name in formats:
        try:
            artifact = word_report.export_word(report, report_dir) if format_name == "word" else pdf_report.export_pdf(report, report_dir)
            result.artifacts.append(artifact)
            artifact_store.register(session_id, artifact.artifact_id, artifact)
        except Exception as exc:
            export_errors.append(f"{format_name}: {exc}")
            logger.warning("report.export.format_failed | 单个格式导出失败 | 分析ID=%s | 格式=%s | 异常类型=%s", analysis.analysis_id, format_name, type(exc).__name__)
    result.stage_status["export"] = "completed" if not export_errors else ("partial_failed" if result.artifacts else "failed")
    result.errors.extend(export_errors)
    logger.info("report.export.%s | 报告导出完成 | 分析ID=%s | 产物数量=%d | 耗时=%d毫秒 | 最终状态=%s", "completed" if not export_errors else result.stage_status["export"], analysis.analysis_id, len(result.artifacts), int((perf_counter() - export_started) * 1000), result.stage_status["export"])
    # 产物在导出时才生成，因此回填到 ReportModel，供结果页渲染下载入口。
    if result.artifacts:
        report = report.model_copy(update={"artifacts": list(result.artifacts)})
    result.report = report
    logger.info("report.workflow.completed | 报告分析流程完成 | 分析ID=%s | 耗时=%d毫秒 | 产物数量=%d | 错误数量=%d", analysis.analysis_id, int((perf_counter() - workflow_started) * 1000), len(result.artifacts), len(result.errors))
    return result
