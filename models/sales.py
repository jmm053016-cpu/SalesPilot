"""定义销售数据导入契约及其日期、粒度和金额约束。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = '1.0'
Grain = Literal['order_line', 'order', 'aggregate']


class ContractModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class DateRange(ContractModel):
    start: date
    end: date

    @model_validator(mode='after')
    def validate_order(self) -> 'DateRange':
        if self.start > self.end:
            raise ValueError('start must be on or before end')
        return self


class ImportOptions(ContractModel):
    source_name: str = Field(min_length=1)
    grain: Grain
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    assume_no_refunds: bool = False
    coverage_start: date | None = None
    coverage_end: date | None = None
    as_of_date: date | None = None
    included_statuses: list[str] | None = None

    @field_validator('currency')
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @model_validator(mode='after')
    def validate_coverage(self) -> 'ImportOptions':
        if self.coverage_start and self.coverage_end and self.coverage_start > self.coverage_end:
            raise ValueError('coverage_start must be on or before coverage_end')
        if self.as_of_date and self.coverage_start and self.as_of_date < self.coverage_start:
            raise ValueError('as_of_date must not precede coverage_start')
        return self


class RawDataset:
    def __init__(self, df: Any, options: ImportOptions) -> None:
        if not hasattr(df, 'columns') or not hasattr(df, 'iloc'):
            raise TypeError('df must be a pandas DataFrame')
        self.df = df
        self.options = options

    def to_dict(self) -> dict[str, Any]:
        raise TypeError('RawDataset must be persisted through DatasetRef before serialization')


class AnalysisAssumptions(ContractModel):
    assume_no_refunds: bool = False
    confirmed_coverage: DateRange | None = None
    as_of_date: date | None = None


class ColumnMapping(ContractModel):
    mapping: dict[str, str]


class AnomalyConfig(ContractModel):
    window_days: int = Field(default=28, ge=1)
    min_history: int = Field(default=14, ge=1)
    medium_z: Decimal = Field(default=Decimal('2'), ge=0)
    high_z: Decimal = Field(default=Decimal('3'), ge=0)
    relative_drop: Decimal = Field(default=Decimal('0.30'), ge=0)
    absolute_drop: Decimal = Field(default=Decimal('1000'), ge=0)

    @model_validator(mode='after')
    def validate_z_thresholds(self) -> 'AnomalyConfig':
        if self.medium_z > self.high_z:
            raise ValueError('medium_z must not exceed high_z')
        return self


class DatasetRef(ContractModel):
    dataset_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)


class DatasetProfile(ContractModel):
    schema_version: str = SCHEMA_VERSION
    dataset_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    rows: int = Field(ge=0)
    columns: list[str]
    grain: Grain
    currency: str | None = None
    min_date: date | None = None
    max_date: date | None = None
    available_metrics: list[str]
    unavailable_metrics: dict[str, str]


class ValidationIssue(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    row_numbers: list[int] = Field(default_factory=list)
    field: str | None = None


class ValidationResult(ContractModel):
    schema_version: str = SCHEMA_VERSION
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    profile: DatasetProfile | None = None
