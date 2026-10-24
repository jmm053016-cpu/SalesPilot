from __future__ import annotations

import pytest

from agent.context import get_runtime_context, require_runtime_context, runtime_context
from agent.state import AgentState, InMemorySaver


def test_agent_state_stores_only_server_side_references() -> None:
    state: AgentState = {
        "messages": [],
        "dataset_id": "dataset-1",
        "analysis_id": "analysis-1",
        "report_id": "report-1",
    }

    saver = InMemorySaver()
    saver.put(session_id="session-a", thread_id="thread-a", state=state)
    loaded = saver.get(session_id="session-a", thread_id="thread-a")

    assert loaded == state
    assert "absolute_path" not in loaded


def test_in_memory_saver_isolated_by_session_and_returns_copies() -> None:
    saver = InMemorySaver()
    saver.put(
        session_id="session-a",
        thread_id="thread-a",
        state={"dataset_id": "dataset-a"},
    )
    saver.put(
        session_id="session-b",
        thread_id="thread-a",
        state={"dataset_id": "dataset-b"},
    )

    loaded = saver.get(session_id="session-a", thread_id="thread-a")
    loaded["dataset_id"] = "mutated"

    assert saver.get(session_id="session-a", thread_id="thread-a")["dataset_id"] == "dataset-a"
    assert saver.get(session_id="session-b", thread_id="thread-a")["dataset_id"] == "dataset-b"


def test_runtime_context_exposes_identity_and_restores_afterward() -> None:
    assert get_runtime_context() is None
    with runtime_context("session-a", "thread-a") as context:
        assert context == require_runtime_context()
        assert context.session_id == "session-a"
        assert context.thread_id == "thread-a"
    assert get_runtime_context() is None


def test_runtime_context_requires_both_ids() -> None:
    with pytest.raises(ValueError, match="session_id"):
        with runtime_context("", "thread-a"):
            pass
    with pytest.raises(ValueError, match="thread_id"):
        with runtime_context("session-a", ""):
            pass
    with pytest.raises(RuntimeError, match="context"):
        require_runtime_context()


def test_model_deadline_rejects_elapsed_calls() -> None:
    from time import sleep

    from agent.middleware import ModelTimeoutError, model_deadline

    with pytest.raises(ModelTimeoutError):
        with model_deadline(0.02):
            sleep(0.05)
