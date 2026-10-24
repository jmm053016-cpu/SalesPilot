"""定义工作台的全局样式与主题呈现规则。"""

from __future__ import annotations

from collections.abc import Iterable


def source_option_cards() -> list[dict[str, str]]:
    """Return the three supported source choices for the card-style selector."""
    return [
        {
            "value": "CSV",
            "extension": ".csv",
            "description": "通用表格数据",
            "icon_svg": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3h10l4 4v14H5z"/><path d="M15 3v5h5M8 12h8M8 16h6"/></svg>',
        },
        {
            "value": "Excel",
            "extension": ".xlsx",
            "description": "工作簿与工作表",
            "icon_svg": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="1"/><path d="M8 8h8M8 12h8M8 16h8M12 8v8"/></svg>',
        },
        {
            "value": "SQLite",
            "extension": ".db",
            "description": "本地订单数据库",
            "icon_svg": '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>',
        },
    ]


def build_stage_statuses(*, dataset_id: str | None, analysis_id: str | None) -> list[tuple[str, str]]:
    """Return the visual progress state for the primary workbench journey."""
    if not dataset_id:
        return [
            ("数据源", "active"),
            ("字段校验", "pending"),
            ("分析配置", "pending"),
            ("结果洞察", "pending"),
            ("报告导出", "pending"),
        ]
    if not analysis_id:
        return [
            ("数据源", "done"),
            ("字段校验", "done"),
            ("分析配置", "active"),
            ("结果洞察", "pending"),
            ("报告导出", "pending"),
        ]
    return [
        ("数据源", "done"),
        ("字段校验", "done"),
        ("分析配置", "done"),
        ("结果洞察", "active"),
        ("报告导出", "pending"),
    ]


def theme_css() -> str:
    """Return the shared Streamlit theme and workbench layout styles."""
    return """
    <style>
    :root {
      --cb-space-1: 0.25rem;
      --cb-space-2: 0.5rem;
      --cb-space-3: 0.75rem;
      --cb-space-4: 1rem;
      --cb-space-6: 1.5rem;
      --cb-space-8: 2rem;
      --cb-space-12: 3rem;
      --cb-ink: #17211f;
      --cb-muted: #66736e;
      --cb-paper: #f3f4f2;
      --cb-surface: #fbfcfa;
      --cb-line: #d9dedb;
      --cb-accent: #d97732;
      --cb-accent-dark: #a94f1e;
      --cb-teal: #1f5c59;
      --cb-success: #2f7558;
      --cb-danger: #ae493f;
    }
    .stApp { background: var(--cb-paper); color: var(--cb-ink); }
    .stApp, .stApp * { font-family: "Microsoft YaHei", "Noto Sans SC", "Segoe UI", sans-serif; letter-spacing: 0; }
    .stApp code, .stApp pre { font-family: Consolas, "SFMono-Regular", monospace; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stSidebar"] { background: #182321; }
    [data-testid="stSidebar"] > div:first-child { background: #182321; }
    [data-testid="stSidebar"] * { color: #f5f3ee !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span { color: #f5f3ee !important; }
    [data-testid="stSidebar"] code { color: #17211f !important; background: #e9eeeb !important; border: 0 !important; }
    [data-testid="stSidebar"] .cb-status { color: #163d31 !important; background: #dcefe4 !important; }
    [data-testid="stSidebar"] .cb-status.warn { color: #713614 !important; background: #f9dfc9 !important; }
    [data-testid="stSidebar"] button, [data-testid="stSidebar"] button p, [data-testid="stSidebar"] button span { color: #f5f3ee !important; }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: #a9b8b1 !important; }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #a9b8b1; }
    [data-testid="stSidebar"] hr { border-color: #344640; margin: .8rem 0; }
    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding: .85rem .75rem 1rem; }
    [data-testid="stSidebar"] .cb-sidebar-shell { min-height: 0; display: flex; flex-direction: column; }
    [data-testid="stSidebar"] .cb-sidebar-brand { display: flex; align-items: center; gap: .75rem; padding: .15rem .2rem .45rem; }
    [data-testid="stSidebar"] .cb-sidebar-brand-mark { display: grid; place-items: center; width: 2.45rem; height: 2.45rem; flex: 0 0 2.45rem; color: #f7eee4 !important; background: #29413a; border: 1px solid #3c5a50; border-radius: 8px; }
    [data-testid="stSidebar"] .cb-sidebar-brand-mark svg { width: 1.45rem; height: 1.45rem; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    [data-testid="stSidebar"] .cb-sidebar-title { color: #f5f3ee !important; font-size: 1.28rem; line-height: 1.15; font-weight: 800; }
    [data-testid="stSidebar"] .cb-sidebar-subtitle { color: #a9b8b1 !important; font-size: .74rem; margin-top: .18rem; line-height: 1.35; }
    [data-testid="stSidebar"] .cb-sidebar-agent { display: flex; align-items: center; gap: .45rem; color: #c2d8cd !important; font-size: .76rem; margin: .55rem .2rem .1rem; }
    [data-testid="stSidebar"] .cb-sidebar-agent span { width: .45rem; height: .45rem; flex: 0 0 .45rem; border-radius: 50%; background: #75bd92; }
    [data-testid="stSidebar"] .cb-sidebar-agent.is-disconnected { color: #e4b38d !important; }
    [data-testid="stSidebar"] .cb-sidebar-agent.is-disconnected span { background: #d97732; }
    [data-testid="stSidebar"] .cb-sidebar-section-title { margin: .2rem .15rem .65rem; color: #f5f3ee !important; font-size: .95rem; line-height: 1.35; font-weight: 750; }
    [data-testid="stSidebar"] .cb-sidebar-empty { padding: .65rem .35rem; color: #a9b8b1 !important; font-size: .8rem; line-height: 1.5; }
    [data-testid="stSidebar"] .cb-sidebar-workspace { display: grid; gap: .65rem; padding: .35rem 0; }
    [data-testid="stSidebar"] .cb-sidebar-workspace div { display: grid; gap: .2rem; min-width: 0; }
    [data-testid="stSidebar"] .cb-sidebar-workspace span { color: #a9b8b1 !important; font-size: .72rem; }
    [data-testid="stSidebar"] .cb-sidebar-workspace strong { overflow: hidden; color: #f5f3ee !important; font-size: .8rem; font-weight: 600; text-overflow: ellipsis; }
    [data-testid="stSidebar"] .cb-sidebar-workspace code { overflow: hidden; color: #dce7e1 !important; background: transparent !important; padding: 0; font-size: .76rem; text-overflow: ellipsis; }
    [data-testid="stSidebar"] .cb-sidebar-footer { margin-top: .65rem; padding: .6rem .15rem 0; color: #879990 !important; font-size: .68rem; }
    [data-testid="stSidebar"] div.stButton > button { min-height: 2.5rem; padding: .55rem .75rem; border-radius: 8px; font-size: .84rem; font-weight: 600; text-align: left; justify-content: flex-start; }
    [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] { border-color: #d97732; background: #d97732; color: #1e211d !important; }
    [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p,
    [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] span { color: #1e211d !important; }
    [data-testid="stSidebar"] [data-testid="stBaseButton-primary"]:hover { border-color: #ed9452; background: #ed9452; }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] { border-color: transparent; background: transparent; color: #e4eae6 !important; }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] p,
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] span { color: #e4eae6 !important; }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover { border-color: #344b43; background: #23342e; }
    [data-testid="stSidebar"] [data-testid="stButton"] { margin-bottom: .08rem; }
    [data-testid="stSidebar"] [data-testid="stSelectbox"] label,
    [data-testid="stSidebar"] [data-testid="stTextInput"] label { color: #b9c8c0 !important; font-size: .8rem; font-weight: 650; }
    [data-testid="stSidebar"] [data-testid="stSelectbox"] label,
    [data-testid="stSidebar"] [data-testid="stTextInput"] label { color: #b9c8c0 !important; font-size: .8rem; font-weight: 650; }
    [data-testid="stSidebar"] [data-testid="stTextInput"] input {
      min-height: 2.55rem;
      background: #20302c !important;
      border: 1px solid #38504a !important;
      border-radius: 8px !important;
      color: #f5f3ee !important;
      font-size: .86rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stTextInput"] input::placeholder { color: #f5f3ee !important; }
    [data-testid="stSidebar"] [data-testid="stTextInput"] input:focus { border-color: #d97732 !important; box-shadow: 0 0 0 1px #d97732 !important; }
    [data-testid="stSidebar"] [data-testid="stTextInput"] > div > div { background: transparent !important; }
    [data-testid="stSidebar"] [data-testid="stExpander"] { border: 1px solid #344640; border-radius: 8px; background: #1c2a26; }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary { min-height: 2.45rem; }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover { color: #fffdf8; background: #23342e; }
    .block-container { max-width: 1400px; padding: 2.25rem 4rem 4rem; }
    h1, h2, h3 { color: var(--cb-ink); letter-spacing: 0; }
    h1 { font-size: clamp(2.15rem, 3.2vw, 3.2rem); line-height: 1.05; }
    h2 { margin-top: 2.2rem; font-size: 1.7rem; line-height: 1.2; }
    h3 { margin-top: 1.5rem; font-size: 1.2rem; line-height: 1.3; }
    [data-testid="stMetric"] { background: var(--cb-surface); border: 1px solid var(--cb-line); border-radius: 8px; padding: 1rem 1.1rem; }
    [data-testid="stMetricLabel"] { color: var(--cb-muted); }
    [data-testid="stMetricValue"] { color: var(--cb-teal); }
    .cb-hero { padding: 0 0 1.25rem; border-bottom: 1px solid var(--cb-line); margin-bottom: 1rem; }
    .cb-hero-kicker { color: var(--cb-accent-dark); font-size: .76rem; font-weight: 700; letter-spacing: 0; text-transform: uppercase; margin-bottom: .7rem; }
    .cb-hero-title { font-size: clamp(1.9rem, 2.7vw, 2.8rem); font-weight: 800; line-height: 1.12; letter-spacing: 0; margin: 0; }
    .cb-hero-copy { color: var(--cb-muted); font-size: .94rem; max-width: 60rem; margin-top: .65rem; }
    .cb-stage { display: flex; align-items: center; gap: .55rem; padding: .5rem 0; border-bottom: 1px solid var(--cb-line); margin: 0 0 1.5rem; overflow-x: auto; }
    .cb-stage-item { display: flex; align-items: center; gap: .45rem; white-space: nowrap; color: #9aa39f; font-size: .84rem; padding-bottom: .55rem; border-bottom: 2px solid transparent; }
    .cb-stage-item.active { color: var(--cb-accent-dark); font-weight: 700; border-bottom-color: var(--cb-accent); }
    .cb-stage-item.done { color: #3d4844; }
    .cb-stage-dot { width: .52rem; height: .52rem; border-radius: 50%; border: 1px solid #b7c0bb; background: transparent; }
    .cb-stage-item.active .cb-stage-dot { border-color: var(--cb-accent); background: var(--cb-accent); }
    .cb-stage-item.done .cb-stage-dot { border-color: #3d4844; background: #3d4844; }
    .cb-stage-connector { width: 1.4rem; height: 1px; flex: 0 0 1.4rem; background: #c5ccc8; }
    .cb-section-lead { color: var(--cb-muted); margin-top: -.6rem; margin-bottom: var(--cb-space-6); font-size: .94rem; line-height: 1.65; }
    .cb-import-mode-label { margin: 0 0 .25rem; color: var(--cb-muted); font-size: .82rem; line-height: 1.4; font-weight: 700; }
    .cb-source-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--cb-space-3); margin: 0 0 var(--cb-space-4); }
    .cb-source-card { display: flex; align-items: center; gap: var(--cb-space-3); min-height: 4.8rem; padding: var(--cb-space-4); background: #f7f9f7; border: 1px solid var(--cb-line); border-radius: 8px; transition: border-color .16s ease, background-color .16s ease; }
    .cb-source-card:hover { border-color: #aab9b1; background: #fbfcfa; }
    .cb-source-card.is-selected { border-color: var(--cb-accent); background: #fff8f0; box-shadow: 0 2px 8px rgba(50,45,38,.05); }
    .cb-source-card-icon { display: grid; place-items: center; width: 2.25rem; height: 2.25rem; color: var(--cb-teal); background: #e7efeb; border-radius: 7px; }
    .cb-source-card.is-selected .cb-source-card-icon { color: var(--cb-accent-dark); background: #f8e8d8; }
    .cb-source-card-icon svg { width: 1.35rem; height: 1.35rem; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
    .cb-source-card-title { color: var(--cb-ink); font-size: .98rem; line-height: 1.35; font-weight: 700; }
    .cb-source-card-meta { color: var(--cb-muted); font-size: .8rem; line-height: 1.45; margin-top: .2rem; }
    [data-testid="stRadio"] { margin-top: .05rem; }
    [data-testid="stRadio"] > div { gap: 1.1rem; }
    [data-testid="stRadio"] label { border: 0; border-radius: 0; padding: .2rem 0; background: transparent; color: var(--cb-muted); font-size: .86rem; line-height: 1.4; font-weight: 600; white-space: nowrap; }
    [data-testid="stRadio"] label:hover { color: var(--cb-ink); }
    [data-testid="stRadio"] label > div:first-child { width: .9rem; height: .9rem; }
    [data-testid="stRadio"] [role="radiogroup"] { align-items: center; }
    .cb-upload { padding: var(--cb-space-6); border: 1px dashed #b9b9af; border-radius: 8px; background: rgba(251,252,250,.72); text-align: center; }
    .cb-upload:hover { border-color: var(--cb-accent); background: #fff8ef; }
    .cb-upload.is-success { border-color: var(--cb-success); background: #edf5ef; }
    .cb-upload.is-error { border-color: var(--cb-danger); background: #fbefed; }
    .cb-upload-empty { display: none; }
    .cb-upload-title { font-weight: 750; color: var(--cb-ink); }
    .cb-upload-copy { color: var(--cb-muted); font-size: .86rem; margin-top: .35rem; }
    .cb-upload-icon { width: 2rem; height: 2rem; margin: 0 auto .65rem; color: #75847d; }
    .cb-upload-icon svg { width: 100%; height: 100%; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
    .cb-upload.is-success .cb-upload-title { color: var(--cb-success); }
    .cb-upload.is-error .cb-upload-title { color: var(--cb-danger); }
    .cb-status { display: inline-flex; align-items: center; gap: .4rem; padding: .32rem .65rem; border-radius: 999px; font-size: .78rem; font-weight: 700; background: #e8eee9; color: var(--cb-success); }
    .cb-status.warn { background: #f9eadf; color: var(--cb-accent-dark); }
    .cb-status.info { background: #e8eef2; color: #315c70; }
    .cb-template-link { display: inline-flex; align-items: center; gap: .3rem; margin: .15rem 0 .65rem; padding: 0; border: 0; background: transparent; color: var(--cb-accent-dark); font-size: .82rem; font-weight: 650; text-decoration: underline; text-underline-offset: 3px; }
    .cb-template-link:hover { color: var(--cb-ink); }
    div.stDownloadButton > button { min-height: auto; padding: 0; border: 0; background: transparent; color: var(--cb-accent-dark); font-size: .82rem; font-weight: 650; text-decoration: underline; text-underline-offset: 3px; }
    div.stDownloadButton > button:hover { border: 0; background: transparent; color: var(--cb-ink); }
    .cb-upload-label { margin: .85rem 0 .4rem; color: var(--cb-ink); font-size: .9rem; line-height: 1.45; font-weight: 700; }
    [data-testid="stFileUploader"] { margin-top: 0; }
    [data-testid="stFileUploader"] section { min-height: 6.5rem; padding: .8rem 1rem; border: 1px dashed #c7cfca; border-radius: 8px; background: #f7f9f7; }
    [data-testid="stFileUploader"] section:hover { border-color: var(--cb-accent); background: #fff8f0; }
    [data-testid="stFileUploader"] small { color: var(--cb-muted); }
    [data-testid="stFileUploader"] button { min-height: 2.25rem; border-radius: 7px; border-color: var(--cb-line); background: #eef2ef; color: var(--cb-ink); }
    [data-testid="stFileUploader"] button:hover { border-color: var(--cb-accent); color: var(--cb-accent-dark); }
    div.stButton > button[kind="primary"] { background: var(--cb-accent); border-color: var(--cb-accent); color: #fffdf8; font-weight: 700; min-height: 3rem; }
    div.stButton > button[kind="primary"]:hover { background: var(--cb-accent-dark); border-color: var(--cb-accent-dark); }
    .stAlert { border-radius: 8px; border: 1px solid var(--cb-line); }
    [data-testid="stAlert"] { color: var(--cb-ink); }
    [data-testid="stAlert"] svg { color: var(--cb-teal); }
    [data-testid="stAlert"]:has(svg[ data-testid="stAlertIcon"] ) { background: var(--cb-surface); }
    [data-testid="stDataFrame"] { border: 1px solid var(--cb-line); border-radius: 8px; overflow: hidden; }
    </style>
    """


def render_stage_bar(
    st,
    *,
    dataset_id: str | None,
    analysis_id: str | None,
    container=None,
) -> None:
    stages: Iterable[tuple[str, str]] = build_stage_statuses(
        dataset_id=dataset_id, analysis_id=analysis_id
    )
    parts: list[str] = []
    for index, (label, status) in enumerate(stages):
        parts.append(
            f'<span class="cb-stage-item {status}"><span class="cb-stage-dot"></span>{label}</span>'
        )
        if index < len(stages) - 1:
            parts.append('<span class="cb-stage-connector" aria-hidden="true"></span>')
    target = container or st
    target.markdown(f'<div class="cb-stage">{"".join(parts)}</div>', unsafe_allow_html=True)

