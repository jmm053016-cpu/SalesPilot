from __future__ import annotations

from pathlib import Path

import pandas as pd

from models.sales import ImportOptions


def options(source_name: str, *, grain: str = "aggregate", currency: str | None = "USD") -> ImportOptions:
    return ImportOptions(source_name=source_name, grain=grain, currency=currency)


def _attach_log_capture(caplog, name: str):
    import logging

    logger = logging.getLogger(name)
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.INFO)
    return logger


def test_csv_preview_maps_fields_and_reports_quality(complete_sales_csv: Path) -> None:
    from ui.data_entry import SourceSelection, build_source_preview

    preview = build_source_preview(
        SourceSelection(kind="csv", path=complete_sales_csv),
        options(complete_sales_csv.name),
    )

    assert preview.validation.valid is True
    assert preview.profile is not None
    assert preview.mapping.mapping["order_date"] == "order_date"
    assert preview.profile.rows == 25


def test_csv_preview_uses_user_selected_mapping(tmp_path: Path) -> None:
    from ui.data_entry import SourceSelection, build_source_preview

    source = tmp_path / "custom.csv"
    source.write_text("when,net\n2024-01-01,19.5\n", encoding="utf-8")

    preview = build_source_preview(
        SourceSelection(kind="csv", path=source),
        options(source.name),
        mapping={"when": "order_date", "net": "sales_amount"},
    )

    assert preview.validation.valid is True
    assert preview.mapping.mapping == {"when": "order_date", "net": "sales_amount"}
    assert list(preview.frame.columns) == ["order_date", "sales_amount"]


def test_csv_preview_rejects_duplicate_standard_field_mapping(tmp_path: Path) -> None:
    import pytest

    from ui.data_entry import SourceSelection, build_source_preview

    source = tmp_path / "custom.csv"
    source.write_text("when,when2,net\n2024-01-01,2024-01-02,19.5\n", encoding="utf-8")

    with pytest.raises(ValueError, match="standard fields must be unique"):
        build_source_preview(
            SourceSelection(kind="csv", path=source),
            options(source.name),
            mapping={
                "when": "order_date",
                "when2": "order_date",
                "net": "sales_amount",
            },
        )


def test_csv_preview_rejects_mapping_for_unknown_source_column(tmp_path: Path) -> None:
    import pytest

    from ui.data_entry import SourceSelection, build_source_preview

    source = tmp_path / "custom.csv"
    source.write_text("when,net\n2024-01-01,19.5\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown source column"):
        build_source_preview(
            SourceSelection(kind="csv", path=source),
            options(source.name),
            mapping={"missing": "order_date", "net": "sales_amount"},
        )


def test_excel_preview_uses_selected_sheet(tmp_path: Path) -> None:
    from ui.data_entry import SourceSelection, build_source_preview

    workbook = tmp_path / "sales.xlsx"
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame({"date": ["2024-01-01"], "sales_amount": [12.5]}).to_excel(
            writer, sheet_name="January", index=False
        )
        pd.DataFrame({"date": ["2024-02-01"], "sales_amount": [20.0]}).to_excel(
            writer, sheet_name="February", index=False
        )

    preview = build_source_preview(
        SourceSelection(kind="excel", path=workbook, sheet_name="February"),
        options(workbook.name),
    )

    assert preview.frame.iloc[0]["sales_amount"] == 20.0
    assert preview.profile.min_date.isoformat() == "2024-02-01"


def test_sqlite_preview_uses_allowlisted_query(tmp_path: Path) -> None:
    import sqlite3
    from ui.data_entry import SourceSelection, build_source_preview

    database = tmp_path / "orders.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE orders (create_time TEXT, amount REAL)")
        connection.execute("INSERT INTO orders VALUES ('2024-01-01', 25.5)")
        connection.commit()

    preview = build_source_preview(
        SourceSelection(kind="sqlite", path=database, query_name="orders"),
        options(database.name, grain="order"),
    )

    assert preview.validation.valid is True
    assert set(preview.frame.columns) == {"order_date", "sales_amount"}


def test_persist_preview_assigns_session_owned_dataset(tmp_path: Path, complete_sales_csv: Path) -> None:
    from storage.datasets import DatasetStore
    from ui.data_entry import SourceSelection, build_source_preview, persist_preview

    preview = build_source_preview(
        SourceSelection(kind="csv", path=complete_sales_csv),
        options(complete_sales_csv.name),
    )
    reference = persist_preview("session-a", preview, DatasetStore(tmp_path))

    assert reference.session_id == "session-a"
    assert reference.dataset_id.startswith("ds_")


def test_preview_logs_source_metadata_without_row_values(tmp_path: Path, caplog) -> None:
    from ui.data_entry import SourceSelection, build_source_preview

    source = tmp_path / "private-name.csv"
    source.write_text("date,sales_amount\n2024-01-01,987654321\n", encoding="utf-8")
    logger = _attach_log_capture(caplog, "salespilot.ui.data_entry")
    try:
        build_source_preview(SourceSelection(kind="csv", path=source), options(source.name))
    finally:
        logger.removeHandler(caplog.handler)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "data_import.preview.started" in messages
    assert "data_import.preview.completed" in messages
    assert "987654321" not in messages
    assert str(source) not in messages


def test_invalid_preview_logs_failure_without_source_content(tmp_path: Path, caplog) -> None:
    import pytest

    from ui.data_entry import SourceSelection, build_source_preview

    source = tmp_path / "sensitive.csv"
    source.write_text("private-header\nconfidential-cell\n", encoding="utf-8")
    logger = _attach_log_capture(caplog, "salespilot.ui.data_entry")
    try:
        with pytest.raises(ValueError):
            build_source_preview(
                SourceSelection(kind="csv", path=source), options(source.name),
                mapping={"missing": "order_date"},
            )
    finally:
        logger.removeHandler(caplog.handler)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "data_import.preview.failed" in messages
    assert "confidential-cell" not in messages
    assert str(source) not in messages


def test_persist_preview_logs_dataset_metadata(tmp_path: Path, complete_sales_csv: Path, caplog) -> None:
    from storage.datasets import DatasetStore
    from ui.data_entry import SourceSelection, build_source_preview, persist_preview

    preview = build_source_preview(SourceSelection(kind="csv", path=complete_sales_csv), options(complete_sales_csv.name))
    logger = _attach_log_capture(caplog, "salespilot.ui.data_entry")
    try:
        ref = persist_preview("session-safe", preview, DatasetStore(tmp_path))
    finally:
        logger.removeHandler(caplog.handler)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "data_import.persist.completed" in messages
    assert ref.dataset_id in messages
    assert "2024-01-01" not in messages


def test_sqlite_preview_keeps_source_order_grain_over_ui_options(tmp_path: Path) -> None:
    import sqlite3

    from ui.data_entry import SourceSelection, build_source_preview

    database = tmp_path / "orders.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE orders (order_id INTEGER, create_time TEXT, amount REAL)"
        )
        connection.execute("INSERT INTO orders VALUES (1, '2024-01-01', 25.5)")
        connection.commit()

    preview = build_source_preview(
        SourceSelection(kind="sqlite", path=database, query_name="orders"),
        options(database.name, grain="aggregate"),
    )

    assert preview.validation.valid is True
    assert preview.profile is not None
    assert preview.profile.grain == "order"
    assert "order_count" in preview.profile.available_metrics
