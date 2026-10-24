from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from agent.analysis_tools import create_analysis_tools
from agent.context import runtime_context
from models.sales import DatasetProfile
from storage.datasets import DatasetStore


def _stores(tmp_path: Path):
    dataset_store = DatasetStore(tmp_path / "datasets")
    profile = DatasetProfile(
        dataset_id="pending",
        session_id="session-a",
        rows=2,
        columns=["order_date", "sales_amount", "category"],
        grain="aggregate",
        currency="USD",
        available_metrics=["sales", "quantity"],
        unavailable_metrics={"orders": "aggregate grain", "profit": "cost unavailable", "yoy": "comparison not requested"},
    )
    df = pd.DataFrame(
        {
            "order_date": ["2024-01-01", "2024-01-02"],
            "sales_amount": [100, 200],
            "category": ["A", "B"],
        }
    )
    ref = dataset_store.save("session-a", df, profile)
    return dataset_store, ref.dataset_id


def test_tools_only_use_current_session_and_return_structured_summary(tmp_path: Path) -> None:
    dataset_store, dataset_id = _stores(tmp_path)
    tools = create_analysis_tools(dataset_store=dataset_store, analysis_root=tmp_path / "analyses")
    inspect, run, export = tools

    with runtime_context("session-a", "thread-a"):
        inspected = inspect.invoke({"dataset_id": dataset_id})
        result = run.invoke(
            {
                "dataset_id": dataset_id,
                "request_json": json.dumps(
                    {
                        "current_start": "2024-01-01",
                        "current_end": "2024-01-31",
                        "comparison": "none",
                        "group_by": ["category"],
                    }
                ),
            }
        )

    assert inspected["ok"] is True
    assert inspected["dataset_id"] == dataset_id
    assert inspected["rows"] == 2
    assert result["ok"] is True
    assert result["analysis_id"].startswith("analysis_")
    assert result["dataset_id"] == dataset_id
    assert result["rankings"][0]["dimension"] == "category"
    assert [item["dimension"] for item in result["rankings"][0]["items"]] == ["B", "A"]
    assert "comparisons" in result
    assert "anomalies" in result


def test_tools_reject_cross_session_and_arbitrary_execution_inputs(tmp_path: Path) -> None:
    dataset_store, dataset_id = _stores(tmp_path)
    tools = create_analysis_tools(dataset_store=dataset_store, analysis_root=tmp_path / "analyses")
    inspect, run, _ = tools

    with runtime_context("session-b", "thread-b"):
        cross_session = inspect.invoke({"dataset_id": dataset_id})
        arbitrary_path = run.invoke(
            {
                "dataset_id": dataset_id,
                "request_json": json.dumps({"path": "C:/secret.csv"}),
            }
        )
        arbitrary_sql = run.invoke(
            {
                "dataset_id": dataset_id,
                "request_json": json.dumps({"sql": "select * from sales"}),
            }
        )

    assert cross_session["ok"] is False
    assert cross_session["error"]["category"] == "unauthorized_dataset"
    assert arbitrary_path["error"]["category"] == "invalid_request"
    assert arbitrary_sql["error"]["category"] == "invalid_request"


def test_export_tool_accepts_only_controlled_format_and_session_context(tmp_path: Path) -> None:
    dataset_store, dataset_id = _stores(tmp_path)
    tools = create_analysis_tools(dataset_store=dataset_store, analysis_root=tmp_path / "analyses")
    _, run, export = tools

    with runtime_context("session-a", "thread-a"):
        result = run.invoke(
            {
                "dataset_id": dataset_id,
                "request_json": json.dumps(
                    {
                        "current_start": "2024-01-01",
                        "current_end": "2024-01-31",
                        "comparison": "none",
                        "group_by": [],
                    }
                ),
            }
        )
        exported = export.invoke({"analysis_id": result["analysis_id"], "format": "xlsx"})

    assert exported["ok"] is False
    assert exported["error"]["category"] == "invalid_format"


def test_export_tool_preserves_original_analysis_id(tmp_path: Path) -> None:
    dataset_store, dataset_id = _stores(tmp_path)
    tools = create_analysis_tools(
        dataset_store=dataset_store,
        analysis_root=tmp_path / "analyses",
        artifact_root=tmp_path / "artifacts",
        report_root=tmp_path / "reports",
    )
    _, run, export = tools

    with runtime_context("session-a", "thread-a"):
        result = run.invoke(
            {
                "dataset_id": dataset_id,
                "request_json": json.dumps(
                    {
                        "current_start": "2024-01-01",
                        "current_end": "2024-01-31",
                        "comparison": "none",
                        "group_by": [],
                    }
                ),
            }
        )
        exported = export.invoke({"analysis_id": result["analysis_id"], "format": "word"})

    assert exported["ok"] is True
    assert exported["analysis_id"] == result["analysis_id"]
