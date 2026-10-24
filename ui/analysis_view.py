"""渲染结构化分析指标、证据、报告下载和工具调用结果。"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent.events import UIEvent
from models.analysis import AnalysisResult, MetricValue
from models.report import ReportModel


def metric_availability_text(metric: MetricValue) -> str:
    if metric.value is None:
        return f"不可用：{metric.reason or '数据不足'}"
    return str(metric.value)


def summarize_tool_events(events: Iterable[UIEvent]) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for event in events:
        if event.type == "tool_started":
            summaries.append({"call_id": event.call_id, "name": event.name, "status": "running"})
        elif event.type == "tool_finished":
            summaries.append({"call_id": event.call_id, "name": event.name, "status": "done"})
        elif event.type == "tool_failed":
            summaries.append({
                "call_id": event.call_id,
                "name": event.name,
                "status": "error",
                "message": str(event.payload.get("message", "tool failed")),
            })
    latest: dict[str, dict[str, str]] = {}
    for item in summaries:
        latest[item["call_id"]] = item
    return list(latest.values())


def _st() -> Any:
    import streamlit as st
    return st


def _render_metric(st: Any, name: str, metric: MetricValue) -> None:
    value = metric_availability_text(metric)
    if metric.value is None:
        st.warning(f"{name}：{value}")
    else:
        st.metric(name, value)


def _render_downloads(st: Any, report: ReportModel, session_id: str) -> None:
    if not report.artifacts:
        st.caption("暂无可下载报告")
        return
    state = getattr(st, "session_state", {})
    artifact_store = state.get("artifact_store") if hasattr(state, "get") else None
    if artifact_store is None:
        st.warning("报告已生成，但当前会话未配置下载存储")
        return
    for artifact in report.artifacts:
        try:
            metadata = artifact_store.resolve(session_id, artifact.artifact_id)
            storage_key = metadata.get("storage_key")
            if not storage_key:
                raise ValueError("artifact storage key is missing")
            path = Path(storage_key)
            if not path.is_file():
                raise FileNotFoundError(storage_key)
            st.download_button(
                label=f"下载 {artifact.display_name}",
                data=path.read_bytes(),
                file_name=artifact.display_name,
                mime=artifact.mime_type,
                key=f"download_{artifact.artifact_id}",
            )
        except Exception as exc:
            st.warning(f"无法下载 {artifact.display_name}：{exc}")


def render_analysis_result(result: AnalysisResult, report: ReportModel | None) -> None:
    """Render the deterministic analysis result and its optional report model.

    The result remains authoritative for metrics, comparisons, rankings, and
    anomalies. Narrative text and artifacts are rendered only when anchored to
    the same analysis and dataset.
    """
    if report is not None and (
        report.analysis_id != result.analysis_id or report.dataset_id != result.dataset_id
    ):
        raise ValueError("report does not belong to analysis result")

    st = _st()
    st.header("结果洞察")
    st.markdown("<div class=\"cb-section-lead\">先看核心指标，再定位变化、排名与异常，最后把结论沉淀为报告。</div>", unsafe_allow_html=True)
    st.caption(
        f"数据集：{result.dataset_id} · 分析期间："
        f"{result.request.current_start.isoformat()} 至 {result.request.current_end.isoformat()}"
    )
    metrics = result.metrics
    if metrics:
        for name, metric in metrics.items():
            _render_metric(st, name, metric)
    else:
        st.info("暂无核心指标")

    st.subheader("期间变化")
    if result.comparisons:
        for item in result.comparisons:
            st.write({
                "维度": item.dimension,
                "当前": metric_availability_text(item.current),
                "上一期间": metric_availability_text(item.previous),
                "变化": metric_availability_text(item.change),
                "完整性": item.completeness,
                "原因": item.reason,
            })
    else:
        st.info("暂无期间对比")

    st.subheader("经营排名")
    if result.rankings:
        for ranking in result.rankings:
            st.write({
                "维度": ranking.dimension,
                "指标": ranking.metric,
                "项目": ranking.items,
            })
    else:
        st.info("暂无排名")

    st.subheader("异常信号")
    if result.anomalies:
        for anomaly in result.anomalies:
            st.warning({
                "维度": anomaly.dimension,
                "期间": f"{anomaly.period.start.isoformat()} 至 {anomaly.period.end.isoformat()}",
                "当前值": str(anomaly.current_value),
                "严重程度": anomaly.severity,
                "原因": anomaly.reason,
            })
    else:
        st.info("暂无异常")

    if report is None or report.narrative is None:
        st.subheader("解读与建议")
        st.info("解读暂不可用：当前没有结构化报告")
    else:
        narrative = report.narrative
        st.subheader("解读与建议")
        st.write(narrative.summary)
        if narrative.observations:
            st.markdown("**观察**")
            for item in narrative.observations:
                st.write(f"- {item.text}")
        if narrative.recommendations:
            st.markdown("**建议**")
            for item in narrative.recommendations:
                st.write(f"- {item.text}")
        if narrative.hypotheses:
            st.markdown("**待验证假设**")
            for item in narrative.hypotheses:
                st.write(f"- {item}")
        if narrative.status == "fallback":
            detail = narrative.diagnostic or "模型未能生成有效解读。"
            st.info(f"模型解读暂不可用，上述内容为确定性事实摘要。原因：{detail}")

    st.subheader("图表视图")
    if report is not None and report.charts:
        for chart in report.charts:
            path = Path(chart.path)
            if path.is_file():
                st.image(str(path), caption=chart.title)
            else:
                st.warning(f"图表文件不存在：{chart.title}")
    else:
        st.info("暂无可用图表")

    st.subheader("报告导出")
    state = getattr(st, "session_state", {})
    session = state.get("analysis_session") if hasattr(state, "get") else None
    session_id = getattr(session, "session_id", None)
    if report is None:
        st.info("暂无可下载报告")
    elif not session_id:
        st.warning("当前会话未绑定 session，无法安全下载报告")
    else:
        _render_downloads(st, report, session_id)
