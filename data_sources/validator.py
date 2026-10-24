"""校验映射后的销售数据，并报告可定位的行级错误与警告。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

from models.sales import (
    ColumnMapping,
    DatasetProfile,
    ImportOptions,
    RawDataset,
    ValidationIssue,
    ValidationResult,
)

REQUIRED_FIELDS = ('order_date', 'sales_amount')


def _issue(code: str, message: str, field: str | None = None, rows: Iterable[int] = ()) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, field=field, row_numbers=list(rows))


def _normalize_columns(frame: pd.DataFrame, mapping: ColumnMapping) -> pd.DataFrame:
    renamed = frame.rename(columns=mapping.mapping).copy()
    for column in renamed.columns:
        if isinstance(column, str):
            renamed.rename(columns={column: column.strip()}, inplace=True)
    return renamed


def _normalize_optional_numeric(
    frame: pd.DataFrame,
    field: str,
    errors: list[ValidationIssue],
) -> None:
    original = frame[field]
    parsed: dict[object, Decimal | None] = {}
    for index, value in original.items():
        if pd.isna(value):
            parsed[index] = None
            continue
        try:
            decimal = Decimal(str(value))
            parsed[index] = decimal if decimal.is_finite() else None
        except (InvalidOperation, ValueError, TypeError):
            parsed[index] = None
    invalid = pd.Series({index: original.loc[index] is not None and not pd.isna(original.loc[index]) and parsed[index] is None for index in original.index})
    invalid_rows = frame.index[invalid].tolist()
    if invalid_rows:
        errors.append(_issue(f'invalid_{field}', f'{field} contains a non-numeric or non-finite value', field, invalid_rows))

    negative_rows = [index for index, value in parsed.items() if value is not None and value < 0]
    if negative_rows:
        errors.append(_issue(f'negative_{field}', f'{field} must be non-negative', field, negative_rows))

    frame[field] = pd.Series(parsed, index=frame.index, dtype=object)


def validate_and_normalize(
    raw: RawDataset,
    mapping: ColumnMapping,
    options: ImportOptions,
) -> tuple[pd.DataFrame, ValidationResult]:
    frame = _normalize_columns(raw.df, mapping)
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    missing = [field for field in REQUIRED_FIELDS if field not in frame.columns]
    for field in missing:
        errors.append(_issue('missing_required_field', f'missing required field: {field}', field))
    if missing:
        profile = DatasetProfile(
            dataset_id='unassigned', session_id='unassigned', rows=len(frame),
            columns=[str(column) for column in frame.columns], grain=options.grain,
            currency=options.currency, min_date=None, max_date=None,
            available_metrics=[], unavailable_metrics={},
        )
        return frame, ValidationResult(valid=False, errors=errors, warnings=warnings, profile=profile)

    parsed_dates = pd.to_datetime(frame['order_date'], errors='coerce')
    bad_dates = frame.index[parsed_dates.isna()].tolist()
    if bad_dates:
        errors.append(_issue('invalid_date', 'order_date contains an unparseable value', 'order_date', bad_dates))
    frame['order_date'] = parsed_dates.dt.date

    parsed_sales: dict[object, Decimal | None] = {}
    for index, value in frame['sales_amount'].items():
        if pd.isna(value):
            parsed_sales[index] = None
            continue
        try:
            amount = Decimal(str(value))
            parsed_sales[index] = amount if amount.is_finite() else None
        except (InvalidOperation, ValueError, TypeError):
            parsed_sales[index] = None
    bad_numeric = [index for index, value in parsed_sales.items() if value is None]
    if bad_numeric:
        errors.append(_issue('invalid_sales_amount', 'sales_amount contains a non-numeric or non-finite value', 'sales_amount', bad_numeric))
    negative = [index for index, value in parsed_sales.items() if value is not None and value < 0]
    if negative:
        errors.append(_issue('negative_sales_amount', 'sales_amount must be non-negative', 'sales_amount', negative))
    frame['sales_amount'] = pd.Series(parsed_sales, index=frame.index, dtype=object)

    if 'currency' in frame.columns:
        currencies = {str(value).strip().upper() for value in frame['currency'].dropna()}
        if options.currency:
            currencies.add(options.currency.upper())
        if len(currencies) > 1:
            errors.append(_issue('mixed_currency', 'dataset contains multiple currencies', 'currency'))
        elif currencies and options.currency is None:
            options = options.model_copy(update={'currency': next(iter(currencies))})
    elif options.currency is None:
        warnings.append(_issue('currency_unconfirmed', 'currency must be confirmed by the user', 'currency'))

    if 'refund_amount' in frame.columns:
        _normalize_optional_numeric(frame, 'refund_amount', errors)
    if 'cost_amount' in frame.columns:
        _normalize_optional_numeric(frame, 'cost_amount', errors)
    if 'quantity' in frame.columns:
        _normalize_optional_numeric(frame, 'quantity', errors)

    available = ['sales']
    unavailable: dict[str, str] = {}
    has_refund_values = 'refund_amount' in frame.columns and frame['refund_amount'].notna().any()
    if has_refund_values or options.assume_no_refunds:
        available.append('net_sales')
    else:
        refund_reason = (
            'refund_amount is empty and no zero-refund assumption was confirmed'
            if 'refund_amount' in frame.columns
            else 'refund_amount is missing and no zero-refund assumption was confirmed'
        )
        unavailable['net_sales'] = refund_reason
    has_cost_values = 'cost_amount' in frame.columns and frame['cost_amount'].notna().any()
    if has_cost_values:
        available.extend(['gross_profit', 'gross_margin'])
    else:
        cost_reason = 'cost_amount is empty' if 'cost_amount' in frame.columns else 'cost_amount is missing'
        unavailable['gross_profit'] = cost_reason
        unavailable['gross_margin'] = cost_reason
    if 'order_id' in frame.columns and options.grain != 'aggregate':
        available.extend(['order_count', 'average_order_value'])
    else:
        unavailable['order_count'] = 'stable order_id is unavailable or dataset grain is aggregate'
        unavailable['average_order_value'] = 'stable order_id is unavailable or dataset grain is aggregate'
    if 'quantity' not in frame.columns:
        unavailable['quantity'] = 'quantity is missing'
    else:
        available.append('quantity')

    valid_dates = [value for value in frame['order_date'].dropna() if isinstance(value, date)]
    profile = DatasetProfile(
        dataset_id='unassigned', session_id='unassigned', rows=len(frame),
        columns=[str(column) for column in frame.columns], grain=options.grain,
        currency=options.currency, min_date=min(valid_dates) if valid_dates else None,
        max_date=max(valid_dates) if valid_dates else None,
        available_metrics=sorted(set(available)), unavailable_metrics=unavailable,
    )
    return frame, ValidationResult(valid=not errors, errors=errors, warnings=warnings, profile=profile)
