from __future__ import annotations

from pathlib import Path

import pytest

from models.sales import ImportOptions
from storage.datasets import DatasetStore


def _options(name: str) -> ImportOptions:
    return ImportOptions(source_name=name, grain="aggregate", currency="USD")


def test_preview_uses_shared_reader_mapping_and_validator(complete_sales_csv: Path) -> None:
    from data_sources.import_service import SourceSelection, build_source_preview

    preview = build_source_preview(
        SourceSelection(kind="csv", path=complete_sales_csv),
        _options(complete_sales_csv.name),
    )

    assert preview.validation.valid
    assert preview.profile is not None
    assert preview.profile.rows == 25
    assert preview.mapping.mapping["order_date"] == "order_date"


def test_invalid_mapping_and_data_never_persist(tmp_path: Path) -> None:
    from data_sources.import_service import SourceSelection, build_source_preview, persist_preview

    invalid_csv = tmp_path / "invalid.csv"
    invalid_csv.write_text("date,sales_amount\nnot-a-date,12\n", encoding="utf-8")
    store = DatasetStore(tmp_path / "datasets")

    invalid_data = build_source_preview(
        SourceSelection(kind="csv", path=invalid_csv), _options(invalid_csv.name)
    )
    with pytest.raises(ValueError, match="cannot persist"):
        persist_preview("session-a", invalid_data, store)

    with pytest.raises(ValueError, match="unknown source column"):
        build_source_preview(
            SourceSelection(kind="csv", path=invalid_csv),
            _options(invalid_csv.name),
            mapping={"missing": "order_date", "sales_amount": "sales_amount"},
        )

    assert not list((tmp_path / "datasets").glob("session-a/*"))


def test_valid_preview_persists_session_owned_dataset(
    tmp_path: Path, complete_sales_csv: Path
) -> None:
    from data_sources.import_service import SourceSelection, build_source_preview, persist_preview

    store = DatasetStore(tmp_path / "datasets")
    preview = build_source_preview(
        SourceSelection(kind="csv", path=complete_sales_csv),
        _options(complete_sales_csv.name),
    )
    reference = persist_preview("session-a", preview, store)

    assert reference.session_id == "session-a"
    assert len(store.load("session-a", reference.dataset_id)) == preview.profile.rows
