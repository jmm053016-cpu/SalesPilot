"""销售经营分析工作台的组合层。

app.py 只负责装配与渲染顺序；「上传 → 自动映射 → 校验落库 → 期间/对比设置 →
确定性流水线 → 结果页」这条主链路集中在这里，避免入口层直接拼装业务细节。

设计约束：
- 数值只来自 analytics/ 的确定性计算；本模块不产生也不推断任何指标。
- 落库必须先过 validate_and_normalize，校验不通过一律不写盘。
- 会话绑定（dataset_id / analysis_id / report_ids）通过不可变会话对象回写。
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from models.analysis import AnalysisRequest
from models.sales import DateRange, ImportOptions
from storage.analyses import AnalysisStore
from storage.artifacts import ArtifactStore
from storage.datasets import DatasetStore
from storage.uploads import UploadStore
from storage.profiles import load_dataset_profile
from workflow.business_report import WorkflowResult, run_business_report
from utils.logging_config import get_logger

from data_sources.mapper import DEFAULT_ALIASES
from .data_entry import SourceSelection, build_source_preview, persist_preview
from .session import AnalysisSession
from .theme import source_option_cards

SOURCE_KINDS = ("csv", "excel", "sqlite")
SOURCE_LABELS = {"CSV": "csv", "Excel": "excel", "SQLite": "sqlite"}
GRAINS = ("order_line", "order", "aggregate")
COMPARISONS = ("none", "mom", "yoy")
COMPARISON_LABELS = {"none": "不对比", "mom": "环比", "yoy": "同比"}
GROUP_CANDIDATES = ("category", "region", "product_name", "order_status", "currency")
logger = get_logger("ui.workbench")
EXPORT_FORMATS = ("word", "pdf")

# data_sources.database_source 只放行 orders 这一条只读查询。
SQLITE_QUERY_NAME = "orders"

UPLOAD_ROOT = ".runtime/uploads"
REPORT_ROOT = ".runtime/reports"

_STATUS_ICONS = {"running": "⏳", "done": "✅", "error": "❌"}


def _st() -> Any:
    import streamlit as st

    return st


# ============================================================
# 纯逻辑：可单测，不依赖 Streamlit
# ============================================================


def sample_csv_template() -> str:
    """Return a small, honest CSV template users can download and edit."""
    return (
        "order_date,order_id,product_name,category,region,quantity,unit_price,sales_amount\n"
        "2024-01-01,ORD-001,示例商品,示例品类,华东,2,99.00,198.00\n"
        "2024-01-02,ORD-002,示例商品B,示例品类,华南,1,158.00,158.00\n"
    )


def save_uploaded_source(
    session_id: str,
    uploaded: Any,
    *,
    upload_root: Path | str = UPLOAD_ROOT,
) -> Path:
    """把上传文件落到会话私有目录，因为 data_sources 只接受真实文件路径。"""
    if not session_id:
        raise ValueError("session_id is required")
    root = Path(upload_root) / session_id
    root.mkdir(parents=True, exist_ok=True)
    name = Path(str(getattr(uploaded, "name", "source.csv"))).name
    suffix = Path(name).suffix.lower() or ".csv"
    target = root / f"source{suffix}"
    buffer = uploaded.getbuffer() if hasattr(uploaded, "getbuffer") else uploaded.read()
    target.write_bytes(bytes(buffer))
    return target


def session_with_run(session: AnalysisSession, workflow: WorkflowResult) -> AnalysisSession:
    """把一次成功的运行结果绑定回会话；失败时原样返回，不清空既有引用。"""
    if workflow.analysis is None:
        return session
    report_ids = [artifact.artifact_id for artifact in workflow.artifacts]
    return replace(
        session,
        analysis_id=workflow.analysis_id or session.analysis_id,
        report_ids=report_ids or session.report_ids,
    )


def clear_dataset_binding(session: AnalysisSession) -> AnalysisSession:
    """解绑数据集与既有分析，用于在同一会话里更换数据源。"""
    return replace(session, dataset_id=None, analysis_id=None, report_ids=[])


def _tool_result(event: Any) -> dict[str, Any] | None:
    """Decode a structured tool result from a normalized stream event."""
    if getattr(event, "type", None) != "tool_finished":
        return None
    content = (getattr(event, "payload", None) or {}).get("content")
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    try:
        result = json.loads(content)
    except (TypeError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def apply_agent_resource_events(
    session: AnalysisSession, events: Any
) -> AnalysisSession:
    """Bind only successful server-issued resources returned by trusted tools."""
    dataset_id = session.dataset_id
    analysis_id = session.analysis_id
    tool_names: dict[str, str] = {}
    for event in events:
        call_id = getattr(event, "call_id", None)
        name = getattr(event, "name", None)
        if getattr(event, "type", None) == "tool_started" and call_id and name:
            tool_names[call_id] = name
        result = _tool_result(event)
        if not result or result.get("ok") is not True:
            continue
        name = name or tool_names.get(call_id)
        if name == "validate_and_save_dataset" and result.get("dataset_id"):
            dataset_id = result["dataset_id"]
        elif name == "run_sales_analysis" and result.get("analysis_id"):
            analysis_id = result["analysis_id"]
            dataset_id = result.get("dataset_id") or dataset_id
        elif result.get("analysis_id"):
            # 分析结果也包含 dataset_id，因此优先根据 analysis_id 识别。
            analysis_id = result["analysis_id"]
            dataset_id = result.get("dataset_id") or dataset_id
        elif result.get("status") == "dataset_saved" and result.get("dataset_id"):
            # 流事件可能缺少工具元数据，仅绑定明确标记为保存成功的数据集。
            dataset_id = result["dataset_id"]
    return replace(session, dataset_id=dataset_id, analysis_id=analysis_id)


class AgentManagedWorkflowError(RuntimeError):
    """保留 Agent 流中断前已完成的资源和事件。"""

    def __init__(self, message: str, session: AnalysisSession, events: list[Any]) -> None:
        super().__init__(message)
        self.session = session
        self.events = events


def execute_agent_managed_workflow(
    agent: Any,
    session: AnalysisSession,
    source_id: str,
    goal: str,
    *,
    stream: Any = None,
) -> tuple[AnalysisSession, list[Any]]:
    """Run the controlled import and analysis tool sequence for one upload."""
    from langchain_core.messages import HumanMessage

    if agent is None:
        raise RuntimeError("Agent 模型不可用，请切换到手动流程。")
    if not source_id or not goal.strip():
        raise ValueError("请提供有效的数据源和分析目标。")
    from agent.agent_setup import reset_agent_thread, stream_agent

    if stream is None:
        stream = stream_agent
    if hasattr(agent, "checkpointer") and hasattr(agent, "_fallback_messages"):
        reset_agent_thread(agent, session.thread_id, session.session_id)
    instruction = (
        f"用户分析目标：{goal.strip()}\n"
        f"当前上传数据源 ID：{source_id}\n"
        "请按流程使用受控工具：先 inspect_import_source；根据字段和样例提出映射，"
        "通过 validate_and_save_dataset 校验并保存；只有工具确认保存成功后，"
        "再依据保存结果的日期覆盖范围和可用字段构造 AnalysisRequest 并调用 run_sales_analysis。"
        "默认按净销售额统计（存在 refund_amount 时使用 sales_amount-refund_amount），"
        "只排除 order_status 中明确表示取消或退款的记录；若样例没有这类状态则保留现有记录。"
        "单一币种直接采用样例币种；分析请求默认覆盖完整可用日期范围、comparison=none，"
        "并选择实际存在的分组字段。只有字段无法映射、存在多币种或存在无法消解的冲突口径时才停止并提问。"
        "coverage=unknown 不得阻止分析完成；change=null 只表示变化率不可用，仍应展示工具已成功返回的绝对值、排名和其他可用结果，"
        "不得仅因覆盖完整性未知而要求用户确认。只有用户明确要求生成变化率时，才说明需确认覆盖范围。"
        "不要自行计算指标；数值只引用分析工具结果。"
        "回答只回复关键结论和必要限制，不要输出原始 JSON、完整请求参数、evidence 或内部 ID。"
        "默认用 1-3 句话概括，只列直接回答问题所需的指标；用户未要求明细时不要展开完整指标清单。"
    )
    instruction += (
        "本次任务中 inspect_import_source、validate_and_save_dataset、run_sales_analysis"
        "各执行必要次数即可；run_sales_analysis 成功返回完整指标和 evidence 后，"
        "直接基于结果回答，不要再调用 inspect_analysis_result。该工具仅用于后续追问。"
    )
    events: list[Any] = []
    try:
        for event in stream(
            agent, [HumanMessage(content=instruction)], session.session_id, session.thread_id
        ):
            events.append(event)
    except Exception as exc:
        updated = apply_agent_resource_events(session, events)
        _log_agent_resource_binding(events, updated)
        raise AgentManagedWorkflowError(str(exc), updated, events) from exc
    updated = apply_agent_resource_events(session, events)
    _log_agent_resource_binding(events, updated)
    return updated, events


def _log_agent_resource_binding(events: list[Any], session: AnalysisSession) -> None:
    counts = {kind: 0 for kind in ("tool_started", "tool_finished", "tool_failed")}
    for event in events:
        kind = getattr(event, "type", None)
        if kind in counts:
            counts[kind] += 1
    logger.info(
        "agent.resources.bound | tool_started=%d | tool_finished=%d | tool_failed=%d "
        "| dataset_bound=%s | analysis_bound=%s",
        counts["tool_started"], counts["tool_finished"], counts["tool_failed"],
        bool(session.dataset_id), bool(session.analysis_id),
    )


def available_group_dimensions(columns: list[str]) -> list[str]:
    """只暴露数据里真实存在的分组维度，避免生成空排名。"""
    return [name for name in GROUP_CANDIDATES if name in columns]


# ============================================================
# 渲染：数据入口
# ============================================================


def render_validation_report(validation: Any) -> None:
    """渲染校验错误、警告与能力清单。"""
    st = _st()
    for issue in validation.errors:
        st.error(f"[{issue.code}] {issue.message}")
    for issue in validation.warnings:
        st.warning(f"[{issue.code}] {issue.message}")
    profile = getattr(validation, "profile", None)
    if profile is None:
        return
    period = (
        f"{profile.min_date} ~ {profile.max_date}"
        if profile.min_date and profile.max_date
        else "未知"
    )
    st.caption(
        f"行数 {profile.rows} · 粒度 {profile.grain} · "
        f"币种 {profile.currency or '未确认'} · 期间 {period}"
    )
    if profile.available_metrics:
        st.write("可用指标：" + "、".join(profile.available_metrics))
    if profile.unavailable_metrics:
        st.write(
            "不可用指标："
            + "；".join(
                f"{name}（{reason}）" for name, reason in profile.unavailable_metrics.items()
            )
        )


def render_data_entry(
    *,
    session: AnalysisSession,
    dataset_store: DatasetStore,
    upload_root: Path | str = UPLOAD_ROOT,
    upload_store: UploadStore | None = None,
    agent: Any | None = None,
    conversation_store: Any | None = None,
) -> AnalysisSession:
    """渲染数据入口：上传 → 自动映射 → 校验 → 落库。

    返回携带 dataset_id 的会话；未完成落库时原样返回入参会话。
    """
    st = _st()
    st.subheader("数据源")
    st.markdown("<div class=\"cb-section-lead\">导入一份可靠的数据，先完成字段识别与质量校验，再进入分析。</div>", unsafe_allow_html=True)
    if session.dataset_id and session.analysis_id:
        st.success(f"数据源已就绪 · {session.dataset_id}")
        st.caption("当前会话的分析、图表与报告都会基于这份数据生成。")
        return session

    mode = "手动映射"
    if agent is not None:
        st.markdown(
            '<div class="cb-import-mode-label">导入方式</div>',
            unsafe_allow_html=True,
        )
        mode = st.radio(
            "导入方式",
            ("Agent 自动分析", "手动映射"),
            horizontal=True,
            key="wb_import_mode",
            label_visibility="collapsed",
        ) or "Agent 自动分析"

    cards = source_option_cards()
    card_markup = "".join(
        f'<div class="cb-source-card{" is-selected" if card["value"] == st.session_state.get("wb_source_kind", "CSV") else ""}">'
        f'<div class="cb-source-card-icon">{card["icon_svg"]}</div>'
        f'<div><div class="cb-source-card-title">{card["value"]}</div>'
        f'<div class="cb-source-card-meta">{card["extension"]} · {card["description"]}</div></div></div>'
        for card in cards
    )
    st.markdown(f'<div class="cb-source-cards">{card_markup}</div>', unsafe_allow_html=True)
    label = st.radio("数据源类型", tuple(SOURCE_LABELS), horizontal=True, key="wb_source_kind", label_visibility="collapsed")
    kind = SOURCE_LABELS[label]
    st.download_button(
        "下载示例 CSV 模板",
        data=sample_csv_template(),
        file_name="salespilot_sales_template.csv",
        mime="text/csv",
        key="wb_download_template",
    )
    st.markdown('<div class="cb-upload-label">上传销售数据文件</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "选择文件",
        type=["csv", "xlsx", "xlsm", "db", "sqlite", "sqlite3"],
        key="wb_source_file",
        label_visibility="collapsed",
    )
    if uploaded is None:
        st.info("请先上传文件。")
        st.button("下一步：开始校验", disabled=True, use_container_width=True, key="wb_next_disabled")
        return session

    try:
        upload_store = upload_store or UploadStore(upload_root)
        content = bytes(uploaded.getbuffer()) if hasattr(uploaded, "getbuffer") else uploaded.read()
        source_key = hashlib.sha256(
            session.session_id.encode("utf-8")
            + str(getattr(uploaded, "name", "source.csv")).encode("utf-8")
            + content
        ).hexdigest()
        source_ref = upload_store.save(
            session.session_id,
            str(getattr(uploaded, "name", "source.csv")),
            content,
            source_key,
        )
        st.session_state["wb_source_id"] = source_ref.source_id
        selection = upload_store.resolve(session.session_id, source_ref.source_id)
        path = selection.path
        st.markdown(f'<div class="cb-upload is-success"><div class="cb-upload-title">上传成功</div><div class="cb-upload-copy">{getattr(uploaded, "name", "文件")} · 已准备校验</div></div>', unsafe_allow_html=True)
    except Exception as exc:  # 上传失败不应影响会话其他状态
        st.markdown('<div class="cb-upload is-error"><div class="cb-upload-title">上传失败</div><div class="cb-upload-copy">请重新选择文件</div></div>', unsafe_allow_html=True)
        st.error(f"保存上传文件失败：{exc}")
        return session

    if agent is not None and mode == "Agent 自动分析":
        goal = st.text_area(
            "分析目标",
            placeholder="例如：分析 2024 年各品类销售额变化，并指出表现较弱的区域",
            key="wb_agent_goal",
        )
        if not st.button("开始自动分析", type="primary", key="wb_agent_run"):
            return session
        if not goal or not goal.strip():
            st.warning("请先描述希望分析的问题。")
            return session
        if conversation_store is not None and session.conversation_id:
            conversation_store.append_message(
                session.session_id,
                session.conversation_id,
                role="user",
                content=goal.strip(),
                metadata={"stage": "agent_analysis_input"},
            )
        try:
            with st.spinner("Agent 正在识别字段、校验数据并执行确定性分析…"):
                updated, events = execute_agent_managed_workflow(
                    agent, session, source_ref.source_id, goal
                )
            st.session_state["wb_agent_events"] = events
            render_tool_events(events)
            answer = "".join(
                str(event.payload.get("delta", ""))
                for event in events
                if getattr(event, "type", None) == "text_delta"
            ).strip()
            if answer:
                st.markdown(answer)
                if conversation_store is not None and session.conversation_id:
                    conversation_store.append_message(
                        session.session_id,
                        session.conversation_id,
                        role="assistant",
                        content=answer,
                        metadata={"stage": "agent_analysis_completed"},
                    )
            if updated.dataset_id and updated.analysis_id:
                st.session_state["wb_agent_managed_completed"] = True
                st.success("数据集已保存，分析结果已生成并绑定到当前会话。")
            elif updated.dataset_id:
                st.warning("数据集已保存，但 Agent 尚未完成分析；当前不会开放结果讨论。请检查 Agent 返回的问题或错误后重新提交自动分析任务。")
            else:
                st.warning("尚未从工具结果中确认已保存的数据集，因此当前会话未绑定分析结果。请检查上方工具调用结果；若保存工具失败，请根据具体错误处理后重试。")
            return updated
        except AgentManagedWorkflowError as exc:
            session = exc.session
            st.session_state["wb_agent_events"] = exc.events
            render_tool_events(exc.events)
            if session.dataset_id and session.analysis_id:
                st.session_state["wb_agent_managed_completed"] = True
                st.warning(f"分析结果已生成并绑定；最终文字总结未完成：{exc}")
                return session
            st.error(f"Agent 自动分析失败：{exc}")
            if conversation_store is not None and session.conversation_id:
                conversation_store.append_message(
                    session.session_id,
                    session.conversation_id,
                    role="error",
                    content=f"Agent 自动分析失败：{exc}",
                    metadata={"stage": "agent_analysis"},
                )
            return session
        except Exception as exc:
            st.error(f"Agent 自动分析失败：{exc}")
            if conversation_store is not None and session.conversation_id:
                conversation_store.append_message(
                    session.session_id,
                    session.conversation_id,
                    role="error",
                    content=f"Agent 自动分析失败：{exc}",
                    metadata={"stage": "agent_analysis"},
                )
            return session

    sheet_name: str | int | None = None
    query_name: str | None = None
    if kind == "excel":
        import pandas as pd

        try:
            sheet_name = st.selectbox("工作表", pd.ExcelFile(path).sheet_names, key="wb_sheet_name")
        except Exception as exc:
            st.error(f"无法读取工作表列表：{exc}")
            return session
    elif kind == "sqlite":
        query_name = SQLITE_QUERY_NAME
        st.caption(f"将执行只读查询：{SQLITE_QUERY_NAME}")

    col_a, col_b, col_c = st.columns(3)
    if kind == "sqlite":
        grain = "order"
        col_a.caption("数据粒度：订单（SQLite 固定）")
    else:
        grain = col_a.selectbox("数据粒度", GRAINS, index=0, key="wb_grain")
    currency_raw = (
        col_b.text_input("币种（3 位字母，留空表示未确认）", value="USD", key="wb_currency")
        .strip()
        .upper()
    )
    assume_no_refunds = col_c.checkbox(
        "确认无退款",
        value=False,
        key="wb_assume_no_refunds",
        help="勾选后缺 refund_amount 时按零退款处理，净销售额才会可用。",
    )

    options = ImportOptions(
        source_name=Path(str(getattr(uploaded, "name", "source"))).name,
        grain=grain,
        currency=currency_raw if len(currency_raw) == 3 else None,
        assume_no_refunds=assume_no_refunds,
    )

    try:
        preview = build_source_preview(
            SourceSelection(kind=kind, path=path, sheet_name=sheet_name, query_name=query_name),
            options,
        )
    except Exception as exc:
        st.error(f"读取或校验失败：{exc}")
        return session

    mapping_title = "字段映射（固定自动识别）" if kind == "sqlite" else "字段映射（自动识别，可手动调整）"
    st.markdown(f"**{mapping_title}**")
    if kind != "sqlite":
        selected_mapping: dict[str, str] = {}
        for index, source_column in enumerate(preview.source_columns):
            automatic = preview.mapping.mapping.get(source_column, "不映射")
            available_options = [
                "不映射",
                *(field for field in DEFAULT_ALIASES if field not in selected_mapping.values()),
            ]
            default_value = automatic if automatic in available_options else "不映射"
            default_index = available_options.index(default_value)
            selected = st.selectbox(
                f"源列：{source_column}",
                available_options,
                index=default_index,
                key=f"wb_mapping_{index}_{source_column}",
            )
            selected = (
                selected if selected in available_options else available_options[default_index]
            )
            if selected != "不映射":
                selected_mapping[source_column] = selected

        mapping_fingerprint = hashlib.sha256(
            repr(
                (
                    kind,
                    options.source_name,
                    options.grain,
                    options.currency,
                    options.assume_no_refunds,
                    tuple(sorted(selected_mapping.items())),
                )
            ).encode("utf-8")
        ).hexdigest()
        confirmation_key = "wb_mapping_confirmation"
        if st.session_state.get(confirmation_key) != mapping_fingerprint:
            if not st.button("下一步：确认字段映射", key="wb_confirm_mapping", use_container_width=True):
                st.info("请确认字段映射后再进行校验和保存。")
                return session
            st.session_state[confirmation_key] = mapping_fingerprint

        try:
            preview = build_source_preview(
                SourceSelection(kind=kind, path=path, sheet_name=sheet_name, query_name=query_name),
                options,
                mapping=selected_mapping,
            )
        except Exception as exc:
            st.error(f"字段映射无效：{exc}")
            return session

    mapping = preview.mapping.mapping
    if mapping:
        st.dataframe(
            {"源列": list(mapping.keys()), "标准字段": list(mapping.values())},
            use_container_width=True,
        )
    else:
        st.warning("未映射到任何标准字段，请至少映射必需字段。")

    render_validation_report(preview.validation)

    st.markdown("**数据预览（前 5 行）**")
    st.dataframe(preview.frame.head(5), use_container_width=True)

    if not preview.validation.valid:
        st.error("校验未通过，无法保存数据集；请修正数据后重新上传。")
        return session

    if not st.button("保存数据集", type="primary", key="wb_persist_preview"):
        return session

    try:
        reference = persist_preview(session.session_id, preview, dataset_store)
    except Exception as exc:
        st.error(f"保存数据集失败：{exc}")
        return session

    st.success(f"数据集已保存：{reference.dataset_id}")
    return replace(session, dataset_id=reference.dataset_id)


# ============================================================
# 渲染：分析设置与执行
# ============================================================


def _picked_period(picked: Any) -> tuple[date, date]:
    if isinstance(picked, (tuple, list)):
        if not picked:
            raise ValueError("分析期间不能为空")
        return picked[0], picked[-1]
    return picked, picked


def render_analysis_controls(
    *,
    session: AnalysisSession,
    dataset_store: DatasetStore,
    analysis_store: AnalysisStore,
    artifact_store: ArtifactStore,
    report_root: Path | str = REPORT_ROOT,
    model: Any | None = None,
) -> WorkflowResult | None:
    """渲染期间/对比/分组/导出设置；点「开始分析」才执行确定性流水线。

    返回 None 表示用户尚未触发分析（或参数不可用）。
    """
    st = _st()
    if not session.dataset_id:
        return None

    try:
        profile = load_dataset_profile(dataset_store, session.session_id, session.dataset_id)
    except Exception as exc:
        st.error(f"无法读取数据集档案：{exc}")
        return None

    st.subheader("分析配置")
    st.markdown("<div class=\"cb-section-lead\">确定分析期间、比较方式与分组维度，生成一份可解释的经营快照。</div>", unsafe_allow_html=True)
    lower = profile.min_date or date.today()
    upper = profile.max_date or date.today()

    picked = st.date_input(
        "分析期间",
        value=(lower, upper),
        min_value=lower,
        max_value=upper,
        key="wb_period",
    )
    try:
        start, end = _picked_period(picked)
    except ValueError as exc:
        st.error(str(exc))
        return None
    if start > end:
        st.error("开始日期不能晚于结束日期。")
        return None

    col_a, col_b = st.columns(2)
    comparison = col_a.selectbox(
        "对比方式",
        COMPARISONS,
        index=0,
        format_func=lambda value: COMPARISON_LABELS[value],
        key="wb_comparison",
    )
    group_dimensions = available_group_dimensions(list(profile.columns))
    group_by = col_b.multiselect(
        "分组维度",
        group_dimensions,
        default=group_dimensions[:2],
        key="wb_group_by",
        help="数据里不存在的维度不会出现，避免生成空排名。",
    )
    formats = st.multiselect(
        "导出格式",
        EXPORT_FORMATS,
        default=["word"],
        key="wb_formats",
        help="不选则只出分析结果，不生成 Word/PDF。",
    )

    st.markdown("<div class=\"cb-section-lead\">将使用确定性分析流水线计算指标、排名、异常，并按需生成报告。</div>", unsafe_allow_html=True)
    if not st.button("运行分析 →", type="primary", key="wb_run_analysis", use_container_width=True):
        return None

    try:
        request = AnalysisRequest(
            dataset_id=session.dataset_id,
            current_start=start,
            current_end=end,
            comparison=comparison,
            group_by=list(group_by),
            confirmed_coverage=DateRange(start=lower, end=upper),
            as_of_date=upper,
        )
    except ValueError as exc:
        st.error(f"分析参数无效：{exc}")
        return None

    with st.spinner("正在执行确定性分析、图表与报告导出…"):
        return run_business_report(
            session.session_id,
            request,
            list(formats),
            dataset_store=dataset_store,
            analysis_store=analysis_store,
            artifact_store=artifact_store,
            output_root=report_root,
            model=model,
        )


# ============================================================
# 渲染：工具事件
# ============================================================


def render_tool_events(events: Any) -> None:
    """按 call_id 归并渲染本轮追问的工具调用状态。"""
    from .analysis_view import summarize_tool_events

    st = _st()
    summaries = summarize_tool_events(events or [])
    if not summaries:
        st.caption("暂无工具调用")
        return
    for item in summaries:
        icon = _STATUS_ICONS.get(item["status"], "•")
        label = f"{icon} {item['name']}"
        message = item.get("message")
        if message:
            st.warning(f"{label}：{message}")
        else:
            st.write(label)
