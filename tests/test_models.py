from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from models.analysis import AnalysisRequest, MetricValue
from models.report import ReportModel
from models.sales import DateRange, ImportOptions


def test_metric_value_serializes_decimal_as_fixed_point_string() -> None:
    metric = MetricValue(value=Decimal('1234.50'), unit='USD')

    assert metric.model_dump(mode='json')['value'] == '1234.50'


def test_date_range_includes_boundaries_and_rejects_reversed_range() -> None:
    period = DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))

    assert period.start == date(2024, 1, 1)
    assert period.end == date(2024, 1, 31)

    with pytest.raises(ValidationError):
        DateRange(start=date(2024, 2, 1), end=date(2024, 1, 31))


def test_unavailable_metric_requires_reason_and_null_value() -> None:
    metric = MetricValue(value=None, unit='USD', reason='缺少退款字段')

    assert metric.value is None
    assert metric.reason == '缺少退款字段'

    with pytest.raises(ValidationError):
        MetricValue(value=None, unit='USD')


def test_unknown_grain_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ImportOptions(source_name='sample.csv', grain='unknown', currency='USD')


def test_analysis_request_rejects_non_finite_threshold() -> None:
    with pytest.raises(ValidationError):
        AnalysisRequest(
            dataset_id='dataset-1',
            current_start=date(2024, 1, 1),
            current_end=date(2024, 1, 31),
            comparison='none',
            group_by=['category'],
            anomaly_threshold=float('nan'),
        )


def test_report_requires_supported_schema_version() -> None:
    with pytest.raises(ValidationError):
        ReportModel(
            schema_version='0.1',
            report_id='report-1',
            analysis_id='analysis-1',
            dataset_id='dataset-1',
            period=DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31)),
        )
