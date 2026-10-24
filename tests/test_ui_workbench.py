"""ui/workbench 组合层测试：数据入口落库、会话绑定、分析流水线接线。"""

from __future__ import annotations

import contextlib
from decimal import Decimal
import io
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from models.sales import ImportOptions
from storage.analyses import AnalysisStore
from storage.artifacts import ArtifactStore
from storage.datasets import DatasetStore
from ui.data_entry import SourceSelection, build_source_preview, persist_preview
from ui.session import create_analysis_session
from ui.workbench import (
    available_group_dimensions,
    clear_dataset_binding,
    render_analysis_controls,
    render_data_entry,
    save_uploaded_source,
    session_with_run,
)
from workflow.business_report import WorkflowResult


class Upload:
    """最小化模拟 Streamlit UploadedFile。"""

    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._buffer = io.BytesIO(data)

    def getbuffer(self):
        return self._buffer.getbuffer()


class Screen:
    """记录调用并按 key 返回预设值的 Streamlit 替身。"""

    def __init__(self, by_key=None, by_name=None, state=None) -> None:
        self.session_state = state if state is not None else {}
        self.by_key = by_key or {}
        self.by_name = by_name or {}
        self.calls: list[tuple[str, tuple, dict]] = []

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [Screen(self.by_key, self.by_name, self.session_state) for _ in range(count)]

    def spinner(self, *args, **kwargs):
        self.calls.append(("spinner", args, kwargs))
        return contextlib.nullcontext()

    def __getattr__(self, name):
        def capture(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            key = kwargs.get("key")
            if key and key in self.by_key:
                return self.by_key[key]
            if name in self.by_name:
                return self.by_name[name]
            return None

        return capture

    def text(self) -> str:
        return str(self.calls)


def _install(monkeypatch, screen) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", screen)


# ============================================================
# 纯逻辑
# ============================================================


def test_save_uploaded_source_writes_into_session_folder(tmp_path: Path) -> None:
    path = save_uploaded_source(
        "session_up", Upload("sales.csv", b"a,b\n1,2\n"), upload_root=tmp_path
    )

    assert path.parent.name == "session_up"
    assert path.name == "source.csv"
    assert path.read_bytes() == b"a,b\n1,2\n"


def test_save_uploaded_source_falls_back_to_csv_suffix(tmp_path: Path) -> None:
    path = save_uploaded_source("session_up", Upload("noext", b"x"), upload_root=tmp_path)

    assert path.suffix == ".csv"


def test_save_uploaded_source_requires_session_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="session_id"):
        save_uploaded_source("", Upload("a.csv", b"x"), upload_root=tmp_path)


def test_session_with_run_binds_analysis_and_report_ids(tmp_path: Path) -> None:
    from datetime import date

    from models.analysis import AnalysisRequest, AnalysisResult, MetricValue
    from models.report import ArtifactRef, ReportModel
    from models.sales import DateRange

    session = create_analysis_session("session_bind")
    analysis = AnalysisResult(
        analysis_id="analysis_bind",
        dataset_id="ds_bind",
        request=AnalysisRequest(
            dataset_id="ds_bind",
            current_start=date(2024, 1, 1),
            current_end=date(2024, 1, 31),
            comparison="none",
            group_by=[],
        ),
        metrics={"sales": MetricValue(value=1, unit="USD")},
    )
    artifact = ArtifactRef(
        artifact_id="artifact_bind",
        kind="report",
        mime_type="application/pdf",
        display_name="report.pdf",
        storage_key=str(tmp_path / "report.pdf"),
    )
    workflow = WorkflowResult(
        analysis_id="analysis_bind",
        analysis=analysis,
        report=ReportModel(
            report_id="report_bind",
            analysis_id="analysis_bind",
            dataset_id="ds_bind",
            period=DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31)),
        ),
        artifacts=[artifact],
    )

    bound = session_with_run(session, workflow)

    assert bound.session_id == "session_bind"
    assert bound.analysis_id == "analysis_bind"
    assert bound.report_ids == ["artifact_bind"]
    # 会话是冻结数据类，绑定必须产生新对象而不是就地修改。
    assert session.analysis_id is None
    assert bound.thread_id == session.thread_id


def test_session_with_run_keeps_session_when_analysis_failed() -> None:
    session = create_analysis_session("session_fail")
    workflow = WorkflowResult(errors=["unauthorized_dataset: nope"])

    assert session_with_run(session, workflow) is session


def test_clear_dataset_binding_keeps_identity_and_thread() -> None:
    session = replace(
        create_analysis_session("session_switch"),
        dataset_id="ds_old",
        analysis_id="analysis_old",
        report_ids=["artifact_old"],
    )

    cleared = clear_dataset_binding(session)

    assert cleared.session_id == "session_switch"
    assert cleared.thread_id == session.thread_id
    assert cleared.dataset_id is None
    assert cleared.analysis_id is None
    assert cleared.report_ids == []
    # 原对象不受影响
    assert session.dataset_id == "ds_old"


def test_available_group_dimensions_only_exposes_present_columns() -> None:
    assert available_group_dimensions(["order_date", "sales_amount", "region"]) == ["region"]
    assert available_group_dimensions(["category", "region", "currency"]) == [
        "category",
        "region",
        "currency",
    ]
    assert available_group_dimensions([]) == []


# ============================================================
# 数据入口渲染
# ============================================================


def test_render_data_entry_persists_valid_dataset_and_binds_it(
    tmp_path: Path, monkeypatch, complete_sales_csv: Path
) -> None:
    screen = Screen(
        by_key={
            "wb_grain": "order_line",
            "wb_currency": "USD",
            "wb_assume_no_refunds": False,
            "wb_confirm_mapping": True,
            "wb_persist_preview": True,
        },
        by_name={"radio": "CSV", "file_uploader": Upload("sales_complete.csv", complete_sales_csv.read_bytes())},
    )
    _install(monkeypatch, screen)
    dataset_store = DatasetStore(tmp_path / "datasets")
    session = create_analysis_session("session_entry")

    updated = render_data_entry(
        session=session, dataset_store=dataset_store, upload_root=tmp_path / "uploads"
    )

    assert updated.dataset_id is not None
    assert updated.dataset_id.startswith("ds_")
    # 落库后能用同一 session 读回数据
    frame = dataset_store.load("session_entry", updated.dataset_id)
    assert len(frame) == 25
    assert "映射" in screen.text()
    assert "可用指标" in screen.text()


def test_render_data_entry_keeps_mapping_confirmation_for_save_rerun(
    tmp_path: Path, monkeypatch, complete_sales_csv: Path
) -> None:
    state = {}
    first_screen = Screen(
        by_key={
            "wb_grain": "order_line",
            "wb_currency": "USD",
            "wb_assume_no_refunds": False,
            "wb_confirm_mapping": True,
            "wb_persist_preview": False,
        },
        by_name={
            "radio": "CSV",
            "file_uploader": Upload("sales_complete.csv", complete_sales_csv.read_bytes()),
        },
        state=state,
    )
    _install(monkeypatch, first_screen)
    dataset_store = DatasetStore(tmp_path / "datasets")
    session = create_analysis_session("session_mapping_rerun")

    pending = render_data_entry(
        session=session, dataset_store=dataset_store, upload_root=tmp_path / "uploads"
    )

    assert pending.dataset_id is None
    assert state["wb_mapping_confirmation"]

    second_screen = Screen(
        by_key={
            "wb_grain": "order_line",
            "wb_currency": "USD",
            "wb_assume_no_refunds": False,
            "wb_confirm_mapping": False,
            "wb_persist_preview": True,
        },
        by_name={
            "radio": "CSV",
            "file_uploader": Upload("sales_complete.csv", complete_sales_csv.read_bytes()),
        },
        state=state,
    )
    _install(monkeypatch, second_screen)

    updated = render_data_entry(
        session=session, dataset_store=dataset_store, upload_root=tmp_path / "uploads"
    )

    assert updated.dataset_id is not None

def test_render_data_entry_refuses_invalid_dataset(
    tmp_path: Path, monkeypatch, invalid_sales_csv: Path
) -> None:
    screen = Screen(
        by_key={
            "wb_grain": "order_line",
            "wb_currency": "USD",
            "wb_assume_no_refunds": False,
            "wb_confirm_mapping": True,
            "wb_persist_preview": True,
        },
        by_name={"radio": "CSV", "file_uploader": Upload("sales_invalid.csv", invalid_sales_csv.read_bytes())},
    )
    _install(monkeypatch, screen)
    dataset_store = DatasetStore(tmp_path / "datasets")
    session = create_analysis_session("session_bad")

    updated = render_data_entry(
        session=session, dataset_store=dataset_store, upload_root=tmp_path / "uploads"
    )

    assert updated.dataset_id is None
    assert "校验未通过" in screen.text()
    # 校验不通过时不得写盘
    assert not list((tmp_path / "datasets" / "session_bad").glob("ds_*"))


def test_render_data_entry_allows_manual_mapping_before_validation(
    tmp_path: Path, monkeypatch
) -> None:
    screen = Screen(
        by_key={
            "wb_grain": "order_line",
            "wb_currency": "USD",
            "wb_assume_no_refunds": False,
            "wb_mapping_0_when": "order_date",
            "wb_mapping_1_net": "sales_amount",
            "wb_confirm_mapping": True,
            "wb_persist_preview": True,
        },
        by_name={
            "radio": "CSV",
            "file_uploader": Upload("custom.csv", b"when,net\n2024-01-01,19.5\n"),
        },
    )
    _install(monkeypatch, screen)
    dataset_store = DatasetStore(tmp_path / "datasets")

    updated = render_data_entry(
        session=create_analysis_session("session_manual"),
        dataset_store=dataset_store,
        upload_root=tmp_path / "uploads",
    )

    assert updated.dataset_id is not None
    frame = dataset_store.load("session_manual", updated.dataset_id)
    assert list(frame.columns) == ["order_date", "sales_amount"]
    assert Decimal(frame.iloc[0]["sales_amount"]) == Decimal("19.5")


def test_render_data_entry_does_not_offer_duplicate_mapping_targets(
    tmp_path: Path, monkeypatch
) -> None:
    screen = Screen(
        by_key={
            "wb_grain": "order_line",
            "wb_currency": "USD",
            "wb_assume_no_refunds": False,
            "wb_mapping_0_when": "order_date",
            "wb_mapping_1_when2": "order_date",
        },
        by_name={
            "radio": "CSV",
            "file_uploader": Upload("custom.csv", b"when,when2\n2024-01-01,2024-01-02\n"),
        },
    )
    _install(monkeypatch, screen)

    render_data_entry(
        session=create_analysis_session("session_mapping_options"),
        dataset_store=DatasetStore(tmp_path / "datasets"),
        upload_root=tmp_path / "uploads",
    )

    second_mapping_options = next(
        call[1][1]
        for call in screen.calls
        if call[0] == "selectbox" and call[2].get("key") == "wb_mapping_1_when2"
    )
    assert "order_date" not in second_mapping_options


def test_render_data_entry_short_circuits_when_dataset_already_bound(
    tmp_path: Path, monkeypatch
) -> None:
    screen = Screen()
    _install(monkeypatch, screen)
    session = replace(
        create_analysis_session("session_ready"),
        dataset_id="ds_ready",
        analysis_id="analysis_ready",
    )

    updated = render_data_entry(
        session=session,
        dataset_store=DatasetStore(tmp_path / "datasets"),
        upload_root=tmp_path / "uploads",
    )

    assert updated is session
    # 已绑定数据集时不再渲染上传控件
    assert not any(call[0] == "file_uploader" for call in screen.calls)


def test_render_data_entry_allows_agent_retry_when_analysis_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    screen = Screen(
        by_key={
            "wb_source_kind": "CSV",
            "wb_import_mode": "Agent 自动分析",
            "wb_source_file": None,
        }
    )
    _install(monkeypatch, screen)
    session = replace(
        create_analysis_session("session_retry"), dataset_id="ds_saved"
    )

    updated = render_data_entry(
        session=session,
        dataset_store=DatasetStore(tmp_path / "datasets"),
        upload_root=tmp_path / "uploads",
        agent=object(),
    )

    assert updated is session
    assert any(call[0] == "file_uploader" for call in screen.calls)


def test_import_mode_heading_is_separate_from_radio_label(tmp_path: Path, monkeypatch) -> None:
    screen = Screen(by_key={"wb_import_mode": "Agent 自动分析", "wb_source_kind": "CSV"})
    _install(monkeypatch, screen)

    render_data_entry(
        session=create_analysis_session("session_import_heading"),
        dataset_store=DatasetStore(tmp_path / "datasets"),
        upload_root=tmp_path / "uploads",
        agent=object(),
    )

    mode_radio_args, mode_radio_kwargs = next(
        (args, kwargs)
        for name, args, kwargs in screen.calls
        if name == "radio" and kwargs.get("key") == "wb_import_mode"
    )
    assert mode_radio_args[0] == "导入方式"
    assert mode_radio_kwargs["label_visibility"] == "collapsed"
    assert any(
        name == "markdown" and "cb-import-mode-label" in args[0]
        for name, args, _ in screen.calls
    )


# ============================================================
# 分析流水线接线
# ============================================================


def _bound_session(tmp_path: Path, complete_sales_csv: Path, session_id: str = "session_run"):
    dataset_store = DatasetStore(tmp_path / "datasets")
    options = ImportOptions(source_name="sales_complete.csv", grain="order_line", currency="USD")
    preview = build_source_preview(SourceSelection(kind="csv", path=complete_sales_csv), options)
    reference = persist_preview(session_id, preview, dataset_store)
    session = replace(create_analysis_session(session_id), dataset_id=reference.dataset_id)
    return session, dataset_store, preview.profile


def test_render_analysis_controls_runs_full_pipeline(
    tmp_path: Path, monkeypatch, complete_sales_csv: Path
) -> None:
    session, dataset_store, profile = _bound_session(tmp_path, complete_sales_csv)
    screen = Screen(
        by_key={
            "wb_period": (profile.min_date, profile.max_date),
            "wb_comparison": "none",
            "wb_group_by": ["category", "region"],
            "wb_formats": ["word"],
            "wb_run_analysis": True,
        }
    )
    _install(monkeypatch, screen)

    workflow = render_analysis_controls(
        session=session,
        dataset_store=dataset_store,
        analysis_store=AnalysisStore(tmp_path / "analyses"),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        report_root=tmp_path / "reports",
    )

    assert workflow is not None
    assert workflow.analysis is not None
    assert workflow.report is not None
    assert workflow.stage_status["analysis"] == "completed"
    assert workflow.stage_status["charts"] == "completed"
    assert workflow.stage_status["export"] == "completed"
    assert workflow.errors == []
    # 数值来自确定性计算，且不因缺少模型而降级
    assert workflow.analysis.metrics["sales"].value is not None
    assert workflow.report.narrative is not None
    assert workflow.report.narrative.status == "fallback"
    # 产物必须回填到报告，否则结果页下载入口为空
    assert len(workflow.report.artifacts) == 1
    assert Path(workflow.report.artifacts[0].storage_key).is_file()

    bound = session_with_run(session, workflow)
    assert bound.analysis_id == workflow.analysis_id
    assert bound.report_ids == [artifact.artifact_id for artifact in workflow.artifacts]


def test_render_analysis_controls_returns_none_without_dataset(tmp_path: Path, monkeypatch) -> None:
    screen = Screen()
    _install(monkeypatch, screen)

    assert (
        render_analysis_controls(
            session=create_analysis_session("session_empty"),
            dataset_store=DatasetStore(tmp_path / "datasets"),
            analysis_store=AnalysisStore(tmp_path / "analyses"),
            artifact_store=ArtifactStore(tmp_path / "artifacts"),
            report_root=tmp_path / "reports",
        )
        is None
    )
    assert screen.calls == []


def test_render_analysis_controls_waits_for_button(
    tmp_path: Path, monkeypatch, complete_sales_csv: Path
) -> None:
    session, dataset_store, profile = _bound_session(tmp_path, complete_sales_csv, "session_wait")
    screen = Screen(
        by_key={
            "wb_period": (profile.min_date, profile.max_date),
            "wb_comparison": "none",
            "wb_group_by": [],
            "wb_formats": [],
            "wb_run_analysis": False,
        }
    )
    _install(monkeypatch, screen)

    workflow = render_analysis_controls(
        session=session,
        dataset_store=dataset_store,
        analysis_store=AnalysisStore(tmp_path / "analyses"),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        report_root=tmp_path / "reports",
    )

    assert workflow is None
    assert not (tmp_path / "reports").exists()
