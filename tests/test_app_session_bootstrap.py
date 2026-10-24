from pathlib import Path

from storage.conversations import ConversationStore


class RecordingLogger:
    def __init__(self):
        self.events = []

    def info(self, message, *args, **kwargs):
        self.events.append(("info", message, args, kwargs))

    def warning(self, message, *args, **kwargs):
        self.events.append(("warning", message, args, kwargs))

    def exception(self, message, *args, **kwargs):
        self.events.append(("exception", message, args, kwargs))


def test_narrative_model_initialization_logs_unavailable(monkeypatch):
    import app

    logger = RecordingLogger()
    monkeypatch.setattr(app, "logger", logger)
    monkeypatch.setattr(app, "create_narrative_model", lambda: None)
    app.init_narrative_model_cached.clear()

    assert app.init_narrative_model_cached() is None
    assert any(event[1].startswith("narrative.model.unavailable") for event in logger.events)


def test_agent_initialization_logs_success(monkeypatch):
    import app

    logger = RecordingLogger()
    monkeypatch.setattr(app, "logger", logger)
    monkeypatch.setattr(app, "create_agent", lambda: object())
    app.init_agent_cached.clear()

    assert app.init_agent_cached() is not None
    assert any(event[1].startswith("agent.initialization.completed") for event in logger.events)


def test_store_initialization_logs_success(monkeypatch):
    import app

    logger = RecordingLogger()
    monkeypatch.setattr(app, "logger", logger)
    for store_name in ("DatasetStore", "AnalysisStore", "ArtifactStore", "ConversationStore"):
        monkeypatch.setattr(app, store_name, lambda: object())
    app.init_stores.clear()

    assert len(app.init_stores()) == 4
    assert any(event[1].startswith("storage.initialization.completed") for event in logger.events)


def test_bootstrap_creates_first_conversation(tmp_path: Path) -> None:
    from app import bootstrap_conversation

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    session = bootstrap_conversation(store, "session_a")

    assert session.session_id == "session_a"
    assert session.conversation_id
    assert store.get("session_a", session.conversation_id) is not None


def test_bootstrap_restores_latest_active_conversation(tmp_path: Path) -> None:
    from app import bootstrap_conversation

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    first = store.create("session_a", title="旧会话")
    store.append_message("session_a", first.conversation_id, role="user", content="旧问题")
    latest = store.create("session_a", title="当前会话")
    store.bind_resources(
        "session_a",
        latest.conversation_id,
        dataset_id="ds_1",
        analysis_id="analysis_1",
        report_ids=["report_1"],
        thread_id="thread_latest",
    )

    restored = bootstrap_conversation(store, "session_a")

    assert restored.conversation_id == latest.conversation_id
    assert restored.dataset_id == "ds_1"
    assert restored.analysis_id == "analysis_1"
    assert restored.report_ids == ["report_1"]
    assert restored.thread_id == "thread_latest"


def test_bootstrap_ignores_deleted_conversation(tmp_path: Path) -> None:
    from app import bootstrap_conversation

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    deleted = store.create("session_a", title="已删除")
    store.soft_delete("session_a", deleted.conversation_id)

    restored = bootstrap_conversation(store, "session_a")

    assert restored.conversation_id
    assert restored.conversation_id != deleted.conversation_id
    assert len(store.list_active("session_a")) == 1


def test_persist_current_binding_updates_conversation(tmp_path: Path) -> None:
    from app import persist_current_binding
    from ui.session import AnalysisSession

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session_a")
    session = AnalysisSession(
        session_id="session_a",
        conversation_id=conversation.conversation_id,
        dataset_id="ds_1",
        analysis_id="analysis_1",
        report_ids=["report_1"],
        thread_id="thread_1",
    )

    persist_current_binding(store, session)
    updated = store.get("session_a", conversation.conversation_id)

    assert updated is not None
    assert updated.dataset_id == "ds_1"
    assert updated.analysis_id == "analysis_1"
    assert updated.report_ids == ["report_1"]
    assert updated.thread_id == "thread_1"


def test_persist_current_binding_ignores_archived_conversation(tmp_path: Path) -> None:
    from app import persist_current_binding
    from ui.session import AnalysisSession

    store = ConversationStore(tmp_path / "conversations.sqlite3")
    conversation = store.create("session_a")
    store.archive("session_a", conversation.conversation_id)
    session = AnalysisSession(
        session_id="session_a",
        conversation_id=conversation.conversation_id,
        dataset_id="ds_1",
        analysis_id="analysis_1",
        report_ids=["report_1"],
        thread_id="thread_1",
    )

    persist_current_binding(store, session)

    restored = store.get("session_a", conversation.conversation_id)
    assert restored is not None
    assert restored.dataset_id is None


def test_browser_workspace_id_restores_session_and_conversation_after_restart(tmp_path: Path) -> None:
    from app import initialize_conversation_state, resolve_workspace_session_id
    from ui.session import create_analysis_session

    params = {}
    identity_path = tmp_path / "workspace_id"
    first_session_id = resolve_workspace_session_id(params, identity_path=identity_path)
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    first_state = {
        "analysis_session": create_analysis_session(first_session_id),
        "conversation_initialized": False,
        "followup_messages": [],
        "followup_events": [],
    }
    initialize_conversation_state(store, first_state)
    first = first_state["analysis_session"]
    store.append_message(first.session_id, first.conversation_id, role="user", content="查看销售趋势")
    store.bind_resources(
        first.session_id,
        first.conversation_id,
        dataset_id="ds_persisted",
        analysis_id="analysis_persisted",
        report_ids=["report_persisted"],
        thread_id="thread_persisted",
    )

    restarted_session_id = resolve_workspace_session_id(params, identity_path=identity_path)
    restarted_state = {
        "analysis_session": create_analysis_session(restarted_session_id),
        "conversation_initialized": False,
        "followup_messages": [],
        "followup_events": [],
    }
    initialize_conversation_state(store, restarted_state)

    restored = restarted_state["analysis_session"]
    assert restarted_session_id == first_session_id
    assert restored.conversation_id == first.conversation_id
    assert restored.dataset_id == "ds_persisted"
    assert restored.analysis_id == "analysis_persisted"
    assert restarted_state["followup_messages"] == [
        {"role": "user", "content": "查看销售趋势"}
    ]


def test_workspace_id_survives_restart_when_browser_query_params_are_lost(tmp_path: Path) -> None:
    from app import resolve_workspace_session_id

    identity_path = tmp_path / "workspace_id"
    first_session_id = resolve_workspace_session_id({}, identity_path=identity_path)

    restarted_session_id = resolve_workspace_session_id({}, identity_path=identity_path)

    assert restarted_session_id == first_session_id
    assert identity_path.read_text(encoding="utf-8") == first_session_id


def test_initialize_conversation_state_restores_saved_analysis(tmp_path: Path) -> None:
    from datetime import date
    from decimal import Decimal

    from app import initialize_conversation_state
    from models.analysis import AnalysisRequest, AnalysisResult, MetricValue
    from storage.analyses import AnalysisStore
    from ui.session import create_analysis_session

    session_id = "session_restore_analysis"
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    analysis_store = AnalysisStore(tmp_path / "analyses")
    conversation = store.create(session_id)
    analysis = AnalysisResult(
        analysis_id="analysis_saved",
        dataset_id="ds_saved",
        request=AnalysisRequest(
            dataset_id="ds_saved",
            current_start=date(2025, 1, 1),
            current_end=date(2025, 1, 31),
            comparison="none",
            group_by=[],
        ),
        metrics={"sales": MetricValue(value=Decimal("123.45"), unit="USD")},
    )
    analysis_store.save(session_id, analysis.analysis_id, analysis)
    store.bind_resources(
        session_id,
        conversation.conversation_id,
        dataset_id="ds_saved",
        analysis_id=analysis.analysis_id,
        report_ids=[],
        thread_id="thread_saved",
    )
    state = {
        "analysis_session": create_analysis_session(session_id),
        "conversation_initialized": False,
        "followup_messages": [],
        "followup_events": [],
    }

    initialize_conversation_state(store, state, analysis_store=analysis_store)

    assert state["analysis_result"].analysis_id == "analysis_saved"
    assert state["analysis_result"].metrics["sales"].value == Decimal("123.45")
from datetime import date
from pathlib import Path

from models.analysis import AnalysisRequest, AnalysisResult, MetricValue
from storage.analyses import AnalysisStore
from ui.session import AnalysisSession


def test_load_archived_analysis_restores_persisted_result(tmp_path: Path) -> None:
    from app import load_archived_analysis

    store = AnalysisStore(tmp_path / "analyses")
    analysis = AnalysisResult(
        analysis_id="analysis_archived",
        dataset_id="ds_archived",
        request=AnalysisRequest(
            dataset_id="ds_archived",
            current_start=date(2024, 1, 1),
            current_end=date(2024, 1, 31),
            comparison="none",
            group_by=[],
        ),
        metrics={"sales": MetricValue(value=120, unit="USD")},
    )
    store.save("session_a", analysis.analysis_id, analysis)

    restored = load_archived_analysis(
        store,
        AnalysisSession(
            session_id="session_a",
            conversation_id="conversation_a",
            dataset_id="ds_archived",
            analysis_id="analysis_archived",
        ),
    )

    assert restored is not None
    assert restored.analysis_id == "analysis_archived"
    assert restored.metrics["sales"].value == 120


def test_load_archived_analysis_returns_none_for_missing_result(tmp_path: Path) -> None:
    from app import load_archived_analysis

    restored = load_archived_analysis(
        AnalysisStore(tmp_path / "analyses"),
        AnalysisSession(
            session_id="session_a",
            conversation_id="conversation_a",
            analysis_id="missing",
        ),
    )

    assert restored is None

