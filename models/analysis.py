"""定义分析请求、指标、证据及分析结果的数据契约。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .sales import ContractModel, DateRange, SCHEMA_VERSION


class MetricValue(ContractModel):
    value: Decimal | None
    unit: str = Field(min_length=1)
    reason: str | None = None

    @field_validator('value')
    @classmethod
    def reject_non_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError('value must be finite')
        return value

    @model_validator(mode='after')
    def validate_availability(self) -> 'MetricValue':
        if self.value is None and not self.reason:
            raise ValueError('reason is required when value is unavailable')
        if self.value is not None and self.reason:
            raise ValueError('reason must be omitted when value is available')
        return self


class Evidence(ContractModel):
    evidence_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: Decimal | None = None
    unit: str | None = None
    period: DateRange | None = None

    @field_validator('value')
    @classmethod
    def reject_non_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError('value must be finite')
        return value


class ComparisonResult(ContractModel):
    dimension: str = Field(min_length=1)
    current: MetricValue
    previous: MetricValue
    change: MetricValue
    completeness: Literal['complete', 'incomplete', 'unknown'] = 'unknown'
    reason: str | None = None


class RankingResult(ContractModel):
    dimension: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    period: DateRange
    items: list[dict[str, MetricValue | str | int | Decimal]] = Field(default_factory=list)


class AnomalyResult(ContractModel):
    anomaly_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    period: DateRange
    current_value: Decimal
    baseline_value: Decimal | None = None
    algorithm: str = Field(min_length=1)
    threshold: Decimal
    severity: Literal['low', 'medium', 'high', 'cold_start']
    reason: str | None = None

    @field_validator('current_value', 'baseline_value', 'threshold')
    @classmethod
    def reject_non_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError('numeric values must be finite')
        return value


class AnalysisRequest(ContractModel):
    dataset_id: str = Field(min_length=1)
    current_start: date
    current_end: date
    comparison: Literal['none', 'mom', 'yoy']
    group_by: list[str]
    anomaly_threshold: Decimal = Field(default=Decimal('0.30'), ge=0)
    absolute_drop_threshold: Decimal = Field(default=Decimal('1000'), ge=0)
    confirmed_coverage: DateRange | None = None
    as_of_date: date | None = None

    @model_validator(mode='after')
    def validate_period(self) -> 'AnalysisRequest':
        if self.current_start > self.current_end:
            raise ValueError('current_start must be on or before current_end')
        if not self.anomaly_threshold.is_finite() or not self.absolute_drop_threshold.is_finite():
            raise ValueError('thresholds must be finite')
        return self


class AnalysisResult(ContractModel):
    schema_version: str = SCHEMA_VERSION
    analysis_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    request: AnalysisRequest
    metrics: dict[str, MetricValue]
    comparisons: list[ComparisonResult] = Field(default_factory=list)
    rankings: list[RankingResult] = Field(default_factory=list)
    anomalies: list[AnomalyResult] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode='after')
    def match_dataset(self) -> 'AnalysisResult':
        if self.request.dataset_id != self.dataset_id:
            raise ValueError('request dataset_id must match result dataset_id')
        return self
