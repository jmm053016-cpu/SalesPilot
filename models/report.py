"""定义叙述、图表和报告产物的结构化数据契约。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from .analysis import AnalysisResult
from .sales import ContractModel, DateRange, SCHEMA_VERSION


class Observation(ContractModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class Recommendation(ContractModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class NarrativeResult(ContractModel):
    summary: str = Field(min_length=1)
    observations: list[Observation] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    status: Literal['generated', 'fallback']
    diagnostic: str | None = None


class ChartArtifact(ContractModel):
    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    path: Path
    mime_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(default_factory=list)


class ArtifactRef(ContractModel):
    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)


class ReportMetadata(ContractModel):
    title: str = Field(min_length=1)
    currency: str | None = None
    generated_at: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class ReportModel(ContractModel):
    schema_version: str = SCHEMA_VERSION
    report_id: str = Field(min_length=1)
    analysis_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    period: DateRange
    analysis: AnalysisResult | None = None
    narrative: NarrativeResult | None = None
    charts: list[ChartArtifact] = Field(default_factory=list)
    metadata: ReportMetadata | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)

    @field_validator('schema_version')
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f'unsupported schema_version: {value}')
        return value
