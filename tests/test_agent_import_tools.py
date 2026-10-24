from __future__ import annotations

import json

from agent.analysis_tools import create_analysis_tools
from agent.context import runtime_context
from storage.datasets import DatasetStore
from storage.uploads import UploadStore


def test_agent_can_inspect_and_save_only_session_owned_upload(tmp_path):
    upload_store = UploadStore(tmp_path / "uploads")
    source = upload_store.save(
        "session-a", "sales.csv",
        b"date,amount\n2024-01-01,12.50\n2024-01-02,18.00\n", "upload-1",
    )
    tools = create_analysis_tools(
        dataset_store=DatasetStore(tmp_path / "datasets"),
        upload_store=upload_store,
        analysis_root=tmp_path / "analyses",
        include_import_tools=True,
    )
    inspect_source, save_dataset = tools[3:5]

    with runtime_context("session-a", "thread-a"):
        inspected = inspect_source.invoke({"source_id": source.source_id})
        saved = save_dataset.invoke({
            "source_id": source.source_id,
            "mapping_json": json.dumps({"date": "order_date", "amount": "sales_amount"}),
            "options_json": json.dumps({"grain": "aggregate", "currency": "USD"}),
            "idempotency_key": "task-1",
        })

    assert inspected["ok"] is True
    assert len(inspected["sample_rows"]) == 2
    assert saved["ok"] is True
    assert saved["dataset_id"].startswith("ds_")


def test_agent_import_tools_reject_cross_session_source_and_invalid_data(tmp_path):
    upload_store = UploadStore(tmp_path / "uploads")
    source = upload_store.save(
        "session-a", "sales.csv", b"date,amount\nnot-a-date,12\n", "upload-1"
    )
    tools = create_analysis_tools(
        dataset_store=DatasetStore(tmp_path / "datasets"), upload_store=upload_store,
        analysis_root=tmp_path / "analyses",
        include_import_tools=True,
    )
    _, save_dataset = tools[3:5]
    args = {
        "source_id": source.source_id,
        "mapping_json": json.dumps({"date": "order_date", "amount": "sales_amount"}),
        "options_json": json.dumps({"grain": "aggregate", "currency": "USD"}),
        "idempotency_key": "task-1",
    }

    with runtime_context("session-b", "thread-b"):
        unauthorized = save_dataset.invoke(args)
    with runtime_context("session-a", "thread-a"):
        invalid = save_dataset.invoke(args)

    assert unauthorized["error"]["category"] == "unauthorized_source"
    assert invalid["error"]["category"] == "validation_failed"
    assert not list((tmp_path / "datasets" / "session-a").glob("ds_*"))


def test_repeating_import_task_returns_the_original_dataset(tmp_path):
    upload_store = UploadStore(tmp_path / "uploads")
    source = upload_store.save(
        "session-a", "sales.csv",
        b"date,amount\n2024-01-01,12.50\n2024-01-02,18.00\n", "upload-1",
    )
    dataset_store = DatasetStore(tmp_path / "datasets")
    tools = create_analysis_tools(
        dataset_store=dataset_store,
        upload_store=upload_store,
        analysis_root=tmp_path / "analyses",
        include_import_tools=True,
    )
    save_dataset = tools[4]
    args = {
        "source_id": source.source_id,
        "mapping_json": json.dumps({"date": "order_date", "amount": "sales_amount"}),
        "options_json": json.dumps({"grain": "aggregate", "currency": "USD"}),
        "idempotency_key": "task-retry",
    }

    with runtime_context("session-a", "thread-a"):
        first = save_dataset.invoke(args)

    restarted_tools = create_analysis_tools(
        dataset_store=DatasetStore(tmp_path / "datasets"),
        upload_store=upload_store,
        analysis_root=tmp_path / "analyses",
        include_import_tools=True,
    )
    args["idempotency_key"] = "different-model-retry-key"
    with runtime_context("session-a", "thread-a"):
        second = restarted_tools[4].invoke(args)

    assert first["dataset_id"] == second["dataset_id"]
    assert len(list((tmp_path / "datasets" / "session-a").glob("ds_*"))) == 1
