"""
SalesPilot - 销售经营分析工作台
Streamlit 主入口

主流程：
    数据入口（上传 → 自动映射 → 校验落库）
      → 分析设置（期间 / 对比 / 分组 / 导出格式）
      → 确定性分析流水线（指标 · 对比 · 排名 · 异常 · 图表 · 解读 · Word/PDF）
      → 结果页与下载
      → 追问（受控工具 + 流式 UIEvent）

架构说明：
- 所有数值由 analytics/ 的确定性代码计算；LLM 不参与数值生成，也不执行任意代码/SQL。
- Agent 只暴露 inspect_dataset / run_sales_analysis / export_business_report 三个受控工具。
- 追问的流式输出走 agent.events 的 UIEvent，工具事件按 call_id 归并展示。
- 数据按 session_id 隔离在 .runtime/ 下，跨会话访问会被存储层拒绝。
- 缺少模型凭据时只禁用追问，确定性分析与报告导出链路照常可用。

运行方式：
    streamlit run app.py --server.address 192.168.1.28 --server.port 8501(不一定行)
    uv run python -m streamlit run .\app.py
"""

# __import__('pysqlite3')
# sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
import os
import re
import sys
import uuid
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

# 必须是第一个 Streamlit 命令，放在其他项目模块导入之前
st.set_page_config(
    page_title="SalesPilot - 销售经营分析工作台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from dotenv import load_dotenv
load_dotenv()

from utils.logging_config import configure_logging, get_logger, safe_exception_summary

logger = get_logger(__name__)
configure_logging()
logger.info("app.startup | 应用启动")

from agent.agent_setup import create_agent, create_narrative_model
from storage.analyses import AnalysisStore
from storage.artifacts import ArtifactStore
from storage.conversations import ConversationStore
from storage.datasets import DatasetStore
from models.analysis import AnalysisResult
from models.report import ArtifactRef, ReportModel
from storage.profiles import load_dataset_profile
from storage.paths import DEFAULT_RUNTIME_ROOT
from ui import (
    clear_analysis_data,
    render_conversation_messages,
    render_conversation_sidebar,
    reset_conversation_view_state,
    switch_conversation,
    clear_dataset_binding,
    create_analysis_session,
    render_analysis_result,
    render_data_entry,
    render_followup_area,
    render_tool_events,
    reset_followup_thread,
    reset_followup_ui,
    session_from_conversation,
    session_to_resource_binding,
)
from ui.theme import render_stage_bar, theme_css


# ============================================================
# 初始化
# ============================================================

WORKSPACE_QUERY_PARAM = "salespilot_workspace"
_WORKSPACE_SESSION_PATTERN = re.compile(r"^session_[0-9a-f]{32}$")


def resolve_workspace_session_id(params=None, *, identity_path: Path | None = None) -> str:
    """优先使用 URL 工作区 ID，并用本地身份文件保证重启后可恢复。"""
    params = st.query_params if params is None else params
    identity_path = Path(identity_path or DEFAULT_RUNTIME_ROOT / "workspace_id")
    candidate = params.get(WORKSPACE_QUERY_PARAM)
    if isinstance(candidate, (list, tuple)):
        candidate = candidate[0] if candidate else None
    candidate = str(candidate).strip() if candidate is not None else ""
    if _WORKSPACE_SESSION_PATTERN.fullmatch(candidate):
        session_id = candidate
    else:
        try:
            persisted = identity_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            persisted = ""
        session_id = persisted if _WORKSPACE_SESSION_PATTERN.fullmatch(persisted) else ""
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex}"
    params[WORKSPACE_QUERY_PARAM] = session_id
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = identity_path.with_name(f"{identity_path.name}.tmp")
    temp_path.write_text(session_id, encoding="utf-8")
    temp_path.replace(identity_path)
    return session_id


@st.cache_resource
def init_stores() -> tuple[DatasetStore, AnalysisStore, ArtifactStore, ConversationStore]:
    """缓存数据、分析、artifact 和会话记录存储句柄。"""
    try:
        stores = DatasetStore(), AnalysisStore(), ArtifactStore(), ConversationStore()
    except Exception as exc:
        logger.exception("storage.initialization.failed | 存储初始化失败 | 错误摘要=%s", safe_exception_summary(exc))
        raise
    logger.info("storage.initialization.completed | 存储初始化完成 | 组件数量=4")
    return stores


def bootstrap_conversation(store: ConversationStore, session_id: str):
    """恢复当前隔离 session 的最近会话；没有时创建一个空会话。"""
    conversations = store.list_active(session_id)
    if conversations:
        return session_from_conversation(conversations[0])
    conversation = store.create(session_id)
    return session_from_conversation(conversation)


def can_render_followup(agent, result) -> bool:
    """只有 Agent 可用且已存在确定性分析结果时才开放结果讨论。"""
    return agent is not None and result is not None


def initialize_conversation_state(
    store: ConversationStore,
    state,
    *,
    analysis_store: AnalysisStore | None = None,
    artifact_store: ArtifactStore | None = None,
) -> None:
    """Create or restore the conversation before any sidebar is rendered."""
    if state.get("conversation_initialized"):
        return
    restored = bootstrap_conversation(
        store,
        state["analysis_session"].session_id,
    )
    state["analysis_session"] = restored
    state["followup_messages"] = restore_conversation_messages(store, restored)
    state["followup_events"] = []
    state["analysis_result"] = (
        load_archived_analysis(analysis_store, restored)
        if analysis_store is not None
        else None
    )
    state["analysis_report"] = (
        load_archived_report(state["analysis_result"], restored, artifact_store)
        if artifact_store is not None
        else None
    )
    state["conversation_initialized"] = True


def persist_current_binding(store: ConversationStore, session) -> None:
    """将当前分析状态中的服务端资源引用同步到持久化会话。"""
    if not session.conversation_id:
        return
    conversation = store.get(session.session_id, session.conversation_id)
    if conversation is None or conversation.status == "archived":
        return
    store.bind_resources(
        session.session_id,
        session.conversation_id,
        **session_to_resource_binding(session),
    )


def restore_conversation_messages(store: ConversationStore, session) -> list[dict[str, str]]:
    """将已持久化消息转换为 Streamlit chat 展示所需的最小结构。"""
    if not session.conversation_id:
        return []
    return [
        {"role": message.role, "content": message.content}
        for message in store.list_messages(session.session_id, session.conversation_id)
    ]


def load_archived_analysis(store: AnalysisStore, session) -> AnalysisResult | None:
    """恢复归档会话的持久化分析结果；缺失或损坏时返回 None。"""
    if not session.analysis_id:
        return None
    try:
        payload = store.get(session.session_id, session.analysis_id)
        return AnalysisResult.model_validate(payload)
    except Exception:
        return None


def load_archived_report(
    analysis: AnalysisResult | None,
    session,
    artifact_store: ArtifactStore,
) -> ReportModel | None:
    """用持久化 artifact 元数据重建归档页可下载报告。"""
    if analysis is None or not session.report_ids:
        return None
    artifacts: list[ArtifactRef] = []
    for artifact_id in session.report_ids:
        try:
            artifacts.append(ArtifactRef.model_validate(
                artifact_store.resolve(session.session_id, artifact_id)
            ))
        except Exception:
            continue
    if not artifacts:
        return None
    return ReportModel(
        report_id=f"archived_{analysis.analysis_id}",
        analysis_id=analysis.analysis_id,
        dataset_id=analysis.dataset_id,
        period={
            "start": analysis.request.current_start,
            "end": analysis.request.current_end,
        },
        analysis=analysis,
        artifacts=artifacts,
    )


def render_archived_conversation(
    session,
    dataset_store: DatasetStore,
    analysis_store: AnalysisStore,
    artifact_store: ArtifactStore,
) -> None:
    """渲染归档会话的完整只读内容，不暴露任何修改入口。"""
    st.info("当前会话已归档，仅可查看历史消息；如需继续分析，请新建会话。")

    if session.dataset_id:
        st.subheader("数据集")
        try:
            profile = load_dataset_profile(dataset_store, session.session_id, session.dataset_id)
            st.write({
                "数据集 ID": profile.dataset_id,
                "数据行数": profile.rows,
                "字段数量": len(profile.columns),
                "字段": profile.columns,
                "日期范围": (
                    f"{profile.min_date} 至 {profile.max_date}"
                    if profile.min_date and profile.max_date else "未识别"
                ),
                "币种": profile.currency or "未指定",
            })
            st.dataframe(dataset_store.load(session.session_id, session.dataset_id).head(5))
        except Exception as exc:
            st.warning(f"无法读取归档数据集：{exc}")

    analysis = load_archived_analysis(analysis_store, session)
    if analysis is None:
        if session.analysis_id:
            st.warning("已绑定分析结果，但分析文件不存在或已损坏。")
        return

    st.session_state.analysis_result = analysis
    report = load_archived_report(analysis, session, artifact_store)
    st.session_state.analysis_report = report
    render_analysis_result(analysis, report)


@st.cache_resource
def init_narrative_model_cached():
    """缓存报告解读模型；缺少 DeepSeek API Key 时返回 None。"""
    try:
        model = create_narrative_model()
    except Exception as exc:
        logger.exception(
            "narrative.model.initialization.failed | 模型初始化失败 | 错误摘要=%s",
            safe_exception_summary(exc),
        )
        return None
    if model is None:
        logger.info("narrative.model.unavailable | 模型解读不可用 | 将使用确定性事实摘要")
    else:
        logger.info("narrative.model.initialization.completed | 模型初始化完成 | 模型=deepseek-flash")
    return model


@st.cache_resource
def init_agent_cached():
    """缓存 Agent 实例；缺少模型凭据时返回 None，工作台仍可完成确定性分析。"""
    try:
        agent = create_agent()
    except Exception as exc:
        logger.exception("agent.initialization.failed | Agent 初始化失败 | 错误摘要=%s", safe_exception_summary(exc))
        return None
    if agent is None:
        logger.info("agent.unavailable | 追问 Agent 不可用 | 仍可执行确定性分析")
    else:
        logger.info("agent.initialization.completed | Agent 初始化完成")
    return agent


def init_session() -> None:
    """初始化 st.session_state。"""
    workspace_session_id = resolve_workspace_session_id()
    defaults = {
        "agent": None,
        "agent_ready": False,
        "analysis_session": create_analysis_session(workspace_session_id),
        "analysis_result": None,
        "analysis_report": None,
        "artifact_store": None,
        "followup_messages": [],
        "followup_events": [],
        "conversation_initialized": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def init_agent() -> None:
    """懒加载 Agent，只尝试一次，避免每轮 rerun 重复构造模型。"""
    if st.session_state.get("agent_ready"):
        return
    st.session_state.agent = init_agent_cached()
    st.session_state.narrative_model = init_narrative_model_cached()
    st.session_state.agent_ready = True


def reset_conversation() -> None:
    """重置追问线程与追问界面，保留当前数据集、分析结果和报告。"""
    session = st.session_state.get("analysis_session")
    if session is not None and st.session_state.get("agent") is not None:
        st.session_state.analysis_session = reset_followup_thread(
            st.session_state.agent, session
        )
    reset_followup_ui(st.session_state)


def clear_current_analysis() -> None:
    """清理当前会话的分析与报告引用，保留数据集以便重新分析。"""
    session = st.session_state.get("analysis_session")
    if session is None:
        return
    clear_analysis_data(
        session,
        analysis_store=AnalysisStore(),
        artifact_store=ArtifactStore(),
    )
    trimmed = replace(session, analysis_id=None, report_ids=[])
    if st.session_state.get("agent") is not None:
        trimmed = reset_followup_thread(st.session_state.agent, trimmed)
    st.session_state.analysis_session = trimmed
    st.session_state.analysis_result = None
    st.session_state.analysis_report = None
    reset_followup_ui(st.session_state)


def switch_dataset() -> None:
    """解绑当前数据集，回到数据入口以更换数据源。"""
    session = st.session_state.get("analysis_session")
    if session is None:
        return
    st.session_state.analysis_session = clear_dataset_binding(session)
    st.session_state.analysis_result = None
    st.session_state.analysis_report = None
    reset_followup_ui(st.session_state)


# ============================================================
# 侧边栏
# ============================================================


def render_sidebar(session, conversation_store: ConversationStore) -> str | None:
    with st.sidebar:
        session_id = str(session.session_id)
        session_display = session_id if len(session_id) <= 24 else f"{session_id[:12]}…{session_id[-8:]}"
        st.markdown(
            '<div class="cb-sidebar-shell">'
            '<div class="cb-sidebar-brand">'
            '<span class="cb-sidebar-brand-mark" aria-hidden="true">'
            '<svg viewBox="0 0 24 24"><path d="M4 19V5M4 19h16M8 15v-4m4 4V7m4 8v-6"/></svg>'
            '</span><div><div class="cb-sidebar-title">SalesPilot</div>'
            '<div class="cb-sidebar-subtitle">销售经营分析工作台</div></div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

        if st.session_state.get("agent") is None:
            st.markdown('<div class="cb-sidebar-agent is-disconnected"><span></span>分析助手未连接</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="cb-sidebar-agent"><span></span>分析助手已连接</div>', unsafe_allow_html=True)

        st.divider()
        selected_conversation = render_conversation_sidebar(
            conversation_store,
            session_id,
            session.conversation_id,
        )

        with st.expander("当前工作区", expanded=False):
            st.markdown(
                '<div class="cb-sidebar-workspace">'
                f'<div><span>数据集</span><strong>{session.dataset_id or "未绑定"}</strong></div>'
                f'<div><span>分析</span><strong>{session.analysis_id or "尚未执行"}</strong></div>'
                f'<div><span>工作区 ID</span><code title="{session_id}">{session_display}</code></div>'
                '</div>',
                unsafe_allow_html=True,
            )

        with st.expander("工作区操作", expanded=False):
            if st.button("重置追问", use_container_width=True):
                reset_conversation()
                st.rerun()
            if session.analysis_id and st.button("清理当前分析数据", use_container_width=True):
                clear_current_analysis()
                st.rerun()
            if session.dataset_id and st.button("更换数据集", use_container_width=True):
                switch_dataset()
                st.rerun()

        with st.expander("工具调用事件", expanded=False):
            render_tool_events(st.session_state.get("followup_events", []))

        st.markdown('<div class="cb-sidebar-footer">SalesPilot · 销售分析工作台</div>', unsafe_allow_html=True)
        return selected_conversation


# ============================================================
# 主流程
# ============================================================


def main() -> None:
    init_session()
    init_agent()

    dataset_store, analysis_store, artifact_store, conversation_store = init_stores()
    # 结果页的下载入口从 session_state 取存储句柄，必须先注入。
    st.session_state.artifact_store = artifact_store

    initialize_conversation_state(
        conversation_store,
        st.session_state,
        analysis_store=analysis_store,
        artifact_store=artifact_store,
    )

    session = st.session_state.analysis_session
    st.markdown(theme_css(), unsafe_allow_html=True)
    selected_conversation = render_sidebar(session, conversation_store)
    if selected_conversation and selected_conversation != session.conversation_id:
        selected_record = conversation_store.get_by_id(selected_conversation)
        if selected_record is None or selected_record.status == "deleted":
            st.rerun()
        switched_session = switch_conversation(
            conversation_store,
            selected_record.session_id,
            selected_record.conversation_id,
        )
        st.session_state.analysis_session = switched_session
        reset_conversation_view_state(st.session_state)
        st.session_state.followup_messages = restore_conversation_messages(
            conversation_store,
            switched_session,
        )
        st.session_state.analysis_result = load_archived_analysis(
            analysis_store,
            switched_session,
        )
        st.session_state.analysis_report = load_archived_report(
            st.session_state.analysis_result,
            switched_session,
            artifact_store,
        )
        st.rerun()

    session = st.session_state.analysis_session
    historical_messages = conversation_store.list_messages(
        session.session_id, session.conversation_id
    ) if session.conversation_id else []
    st.markdown(
        '<section class="cb-hero">'
        '<div class="cb-hero-kicker">SALESPILOT / BUSINESS INTELLIGENCE</div>'
        '<div class="cb-hero-title">销售经营分析工作台</div>'
        '<div class="cb-hero-copy">从数据入口到经营洞察，把每一次分析变成可复用、可追问、可导出的决策依据。</div>'
        '</section>',
        unsafe_allow_html=True,
    )
    stage_slot = st.empty()
    if historical_messages:
        render_conversation_messages(historical_messages)

    current_conversation = conversation_store.get(session.session_id, session.conversation_id)
    if current_conversation is not None and current_conversation.status == "archived":
        render_archived_conversation(
            session,
            dataset_store,
            analysis_store,
            artifact_store,
        )
        return

    # ① 数据入口：上传 → 自动映射 → 校验 → 落库
    updated = render_data_entry(
        session=session,
        dataset_store=dataset_store,
        agent=st.session_state.get("agent"),
        conversation_store=conversation_store,
    )
    # Dataset persistence and analysis can succeed independently; commit either binding change.
    if updated != session:
        st.session_state.analysis_session = updated
        persist_current_binding(conversation_store, updated)
        if updated.analysis_id != session.analysis_id:
            st.session_state.analysis_result = load_archived_analysis(
                analysis_store, updated
            )
            st.session_state.analysis_report = None
        elif updated.dataset_id != session.dataset_id:
            st.session_state.analysis_result = None
            st.session_state.analysis_report = None
    session = st.session_state.analysis_session

    if not session.dataset_id:
        render_stage_bar(
            st,
            dataset_id=session.dataset_id,
            analysis_id=session.analysis_id,
            container=stage_slot,
        )
        st.info("数据集尚未绑定，绑定后才会出现分析设置与追问入口。")
        return

    # ② 分析由前面的 Agent 工作流调度；此处不提供独立手动运行入口。
    result = st.session_state.get("analysis_result")
    if result is None:
        st.info("数据集已保存，Agent 尚未完成分析。完成分析后，结果和讨论入口会显示在这里。")

    render_stage_bar(
        st,
        dataset_id=session.dataset_id,
        analysis_id=session.analysis_id,
        container=stage_slot,
    )

    # ③ 结果页：确定性结果为准，报告承载解读、图表与下载
    if result is not None:
        render_analysis_result(result, st.session_state.get("analysis_report"))

    # ④ 仅在结果可供引用时开放讨论，避免对未完成分析进行无证据追问。
    agent = st.session_state.get("agent")
    if not can_render_followup(agent, result):
        return
    response = render_followup_area(
        agent, session, conversation_store=conversation_store
    )
    if response is not None:
        st.session_state.followup_messages.extend(
            [
                {"role": "user", "content": st.session_state.get("analysis_followup", "")},
                {"role": "assistant", "content": response.text},
            ]
        )
        st.session_state.followup_events.extend(response.events)


if __name__ == "__main__":
    main()
