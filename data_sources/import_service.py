"""Provide UI-independent source preview, validation, and persistence services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import pandas as pd

from data_sources.csv_source import load_csv
from data_sources.database_source import load_sqlite
from data_sources.excel_source import load_excel
from data_sources.mapper import DEFAULT_ALIASES, map_columns
from data_sources.validator import validate_and_normalize
from models.sales import ColumnMapping, DatasetProfile, DatasetRef, ImportOptions, ValidationResult
from storage.datasets import DatasetStore
from utils.logging_config import get_logger

logger = get_logger("ui.data_entry")


@dataclass(frozen=True)
class SourceSelection:
    kind: str
    path: Path | str
    sheet_name: str | int | None = None
    query_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"csv", "excel", "sqlite"}:
            raise ValueError(f"unsupported source kind: {self.kind}")
        if self.kind == "excel" and self.sheet_name is None:
            raise ValueError("sheet_name is required for excel sources")
        if self.kind == "sqlite" and not self.query_name:
            raise ValueError("query_name is required for sqlite sources")


@dataclass(frozen=True)
class SourcePreview:
    frame: pd.DataFrame
    mapping: ColumnMapping
    validation: ValidationResult
    profile: DatasetProfile | None
    source_columns: tuple[str, ...]


def _load(selection: SourceSelection, options: ImportOptions):
    path = Path(selection.path)
    if selection.kind == "csv":
        return load_csv(path, options)
    if selection.kind == "excel":
        return load_excel(path, selection.sheet_name, options)
    return load_sqlite(path, selection.query_name)


def _validate_mapping(raw: pd.DataFrame, mapping: dict[str, str]) -> None:
    source_columns = {str(column) for column in raw.columns}
    unknown = sorted(set(mapping) - source_columns)
    if unknown:
        raise ValueError(f"unknown source column: {unknown[0]}")
    standard_fields = set(DEFAULT_ALIASES)
    invalid = sorted(set(mapping.values()) - standard_fields)
    if invalid:
        raise ValueError(f"unknown standard field: {invalid[0]}")
    targets = list(mapping.values())
    if len(targets) != len(set(targets)):
        raise ValueError("standard fields must be unique")
    renamed_columns = [mapping.get(str(column), str(column)) for column in raw.columns]
    if len(renamed_columns) != len(set(renamed_columns)):
        raise ValueError("standard fields must be unique")


def build_source_preview(
    selection: SourceSelection,
    options: ImportOptions,
    mapping: dict[str, str] | None = None,
) -> SourcePreview:
    started = perf_counter()
    logger.info("data_import.preview.started | 开始预览数据 | 来源类型=%s", selection.kind)
    try:
        raw = _load(selection, options)
        selected_mapping = map_columns(raw.df, {}) if mapping is None else ColumnMapping(mapping=mapping)
        _validate_mapping(raw.df, selected_mapping.mapping)
        validation_options = options
        if selection.kind == "sqlite":
            validation_options = options.model_copy(update={"grain": raw.options.grain})
        frame, validation = validate_and_normalize(raw, selected_mapping, validation_options)
        preview = SourcePreview(
            frame=frame,
            mapping=selected_mapping,
            validation=validation,
            profile=validation.profile if validation.valid else None,
            source_columns=tuple(str(column) for column in raw.df.columns),
        )
    except Exception as exc:
        logger.warning(
            "data_import.preview.failed | 数据预览失败 | 来源类型=%s | 异常类型=%s",
            selection.kind,
            type(exc).__name__,
        )
        raise
    logger.info(
        "data_import.preview.completed | 数据预览完成 | 来源类型=%s | 行数=%d | 列数=%d | 校验通过=%s | 耗时=%d毫秒",
        selection.kind,
        len(preview.frame),
        len(preview.frame.columns),
        preview.validation.valid,
        int((perf_counter() - started) * 1000),
    )
    return preview


def persist_preview(session_id: str, preview: SourcePreview, dataset_store: DatasetStore) -> DatasetRef:
    if not preview.validation.valid or preview.validation.profile is None:
        raise ValueError("cannot persist an invalid source preview")
    profile = preview.validation.profile.model_copy(update={"session_id": session_id})
    try:
        reference = dataset_store.save(session_id, preview.frame, profile)
    except Exception as exc:
        logger.warning("data_import.persist.failed | 数据持久化失败 | 异常类型=%s", type(exc).__name__)
        raise
    logger.info(
        "data_import.persist.completed | 数据保存完成 | 数据集ID=%s | 行数=%d | 列数=%d",
        reference.dataset_id,
        len(preview.frame),
        len(preview.frame.columns),
    )
    return reference
