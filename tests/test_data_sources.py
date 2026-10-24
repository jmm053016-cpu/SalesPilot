from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from models.sales import ImportOptions


def options(*, grain: str = 'aggregate', currency: str | None = 'USD') -> ImportOptions:
    return ImportOptions(source_name='fixture.csv', grain=grain, currency=currency)


def test_load_csv_returns_raw_dataset(complete_sales_csv: Path) -> None:
    from data_sources.csv_source import load_csv

    raw = load_csv(complete_sales_csv, options(grain='aggregate'))

    assert len(raw.df) == 25
    assert 'category' in raw.df.columns


def test_load_excel_supports_selected_sheet(tmp_path: Path) -> None:
    from data_sources.excel_source import load_excel

    workbook = tmp_path / 'sales.xlsx'
    with pd.ExcelWriter(workbook, engine='openpyxl') as writer:
        pd.DataFrame({'date': ['2024-01-01'], 'sales_amount': [12.5]}).to_excel(
            writer, sheet_name='January', index=False
        )
        pd.DataFrame({'date': ['2024-02-01'], 'sales_amount': [20.0]}).to_excel(
            writer, sheet_name='February', index=False
        )

    raw = load_excel(workbook, 'February', options())

    assert raw.df.iloc[0]['sales_amount'] == '20'


def test_load_excel_calculates_formula_columns_without_cached_values(tmp_path: Path) -> None:
    from openpyxl import Workbook
    from data_sources.excel_source import load_excel

    workbook = tmp_path / 'formula_sales.xlsx'
    sheet = Workbook().active
    sheet.title = '销售明细'
    sheet.append(['订单日期', '销售数量', '标准单价', '折扣率', '销售金额', '单位成本', '成本金额', '退款金额', '净销售额'])
    sheet.append(['2024-01-01', 85, 3167, 0.0989, '=B2*C2*(1-D2)', 1972.67, '=B2*F2', 0, '=E2-H2'])
    sheet.parent.save(workbook)

    raw = load_excel(workbook, '销售明细', options(grain='order_line', currency='CNY'))

    row = raw.df.iloc[0]
    assert row['销售金额'] == '242571.6145'
    assert row['成本金额'] == '167676.95'
    assert row['净销售额'] == '242571.6145'


def test_load_excel_rejects_unsupported_formula_instead_of_importing_blank(tmp_path: Path) -> None:
    from openpyxl import Workbook
    from data_sources.excel_source import load_excel

    workbook = tmp_path / "unsupported_formula.xlsx"
    sheet = Workbook().active
    sheet.append(["date", "sales_amount"])
    sheet.append(["2024-01-01", "=SUM(B2:B2)"])
    sheet.parent.save(workbook)

    with pytest.raises(ValueError, match="cannot calculate formula at B2"):
        load_excel(workbook, "Sheet", options())


def test_map_columns_recognizes_supported_aliases(complete_sales_csv: Path) -> None:
    from data_sources.csv_source import load_csv
    from data_sources.mapper import map_columns

    raw = load_csv(complete_sales_csv, options())
    mapping = map_columns(
        raw.df,
        {
            'order_date': ['order_date', 'date'],
            'category': ['category', 'product_category'],
            'region': ['region', 'country'],
            'sales_amount': ['sales_amount'],
            'quantity': ['quantity'],
        },
    )

    assert mapping.mapping['order_date'] == 'order_date'
    assert mapping.mapping['category'] == 'category'
    assert mapping.mapping['region'] == 'region'


def test_validation_normalizes_supported_fields(
    complete_sales_csv: Path,
) -> None:
    from data_sources.csv_source import load_csv
    from data_sources.mapper import map_columns
    from data_sources.validator import validate_and_normalize

    raw = load_csv(complete_sales_csv, options())
    mapping = map_columns(raw.df, {})
    normalized, result = validate_and_normalize(raw, mapping, options())

    assert result.valid is True
    assert {'order_date', 'category', 'region', 'sales_amount', 'quantity'} <= set(normalized.columns)
    assert result.profile is not None
    assert result.profile.grain == 'aggregate'
    assert 'order_count' in result.profile.unavailable_metrics
    assert 'average_order_value' in result.profile.unavailable_metrics


def test_validation_rejects_missing_required_field(tmp_path: Path) -> None:
    from data_sources.csv_source import load_csv
    from data_sources.mapper import map_columns
    from data_sources.validator import validate_and_normalize

    source = tmp_path / 'missing.csv'
    source.write_text('date,category\n2024-01-01,服装\n', encoding='utf-8')
    raw = load_csv(source, options())

    _, result = validate_and_normalize(raw, map_columns(raw.df, {}), options())

    assert result.valid is False
    assert any(issue.code == 'missing_required_field' for issue in result.errors)


def test_validation_rejects_bad_date_and_negative_sales(invalid_sales_csv: Path) -> None:
    from data_sources.csv_source import load_csv
    from data_sources.mapper import map_columns
    from data_sources.validator import validate_and_normalize

    raw = load_csv(invalid_sales_csv, options())
    _, result = validate_and_normalize(raw, map_columns(raw.df, {}), options())

    assert result.valid is False
    codes = {issue.code for issue in result.errors}
    assert 'invalid_date' in codes
    assert 'negative_sales_amount' in codes


def test_validation_rejects_mixed_currency(tmp_path: Path) -> None:
    from data_sources.csv_source import load_csv
    from data_sources.mapper import map_columns
    from data_sources.validator import validate_and_normalize

    source = tmp_path / 'mixed.csv'
    source.write_text(
        'order_date,sales_amount,currency\n2024-01-01,10,USD\n2024-01-02,20,EUR\n',
        encoding='utf-8',
    )
    raw = load_csv(source, options(currency=None))

    _, result = validate_and_normalize(raw, map_columns(raw.df, {}), options(currency=None))

    assert result.valid is False
    assert any(issue.code == 'mixed_currency' for issue in result.errors)


def test_loader_rejects_more_than_100000_rows(tmp_path: Path) -> None:
    from data_sources.csv_source import load_csv

    source = tmp_path / 'large.csv'
    pd.DataFrame({'date': ['2024-01-01'] * 100001, 'sales_amount': [1] * 100001}).to_csv(
        source, index=False
    )

    with pytest.raises(ValueError, match='100,000'):
        load_csv(source, options())


def test_sqlite_loader_uses_controlled_orders_query(tmp_path: Path) -> None:
    from data_sources.database_source import load_sqlite

    database = tmp_path / 'orders.db'
    with sqlite3.connect(database) as connection:
        connection.execute(
            'CREATE TABLE orders (create_time TEXT, amount REAL, country TEXT, product_name TEXT)'
        )
        connection.execute(
            "INSERT INTO orders VALUES ('2024-01-01', 25.5, 'US', 'Mouse')"
        )
        connection.commit()

    raw = load_sqlite(database, 'orders')

    assert len(raw.df) == 1
    assert set(raw.df.columns) >= {'create_time', 'amount'}

    with pytest.raises(ValueError):
        load_sqlite(database, 'arbitrary_sql')


def test_dataset_store_blocks_cross_session_access(tmp_path: Path) -> None:
    from storage.datasets import DatasetStore, UnauthorizedDatasetError
    from models.sales import DatasetProfile

    store = DatasetStore(tmp_path)
    profile = DatasetProfile(
        dataset_id='dataset-1',
        session_id='session-a',
        rows=1,
        columns=['order_date', 'sales_amount'],
        grain='aggregate',
        currency='USD',
        min_date=None,
        max_date=None,
        available_metrics=['sales'],
        unavailable_metrics={},
    )
    frame = pd.DataFrame({'order_date': ['2024-01-01'], 'sales_amount': [10]})
    store.save('session-a', frame, profile)

    with pytest.raises(UnauthorizedDatasetError):
        store.load('session-b', 'dataset-1')


def test_validation_rejects_invalid_and_negative_optional_numeric_fields() -> None:
    from data_sources.mapper import map_columns
    from data_sources.validator import validate_and_normalize
    from models.sales import RawDataset

    frame = pd.DataFrame([
        {
            'order_date': '2024-01-01',
            'sales_amount': '100.00',
            'refund_amount': 'not-a-number',
            'cost_amount': '40.00',
            'quantity': '1',
        },
        {
            'order_date': '2024-01-02',
            'sales_amount': '80.00',
            'refund_amount': '5.00',
            'cost_amount': '-1.00',
            'quantity': '-2',
        },
    ])
    import_options = options(grain='order_line')

    _, result = validate_and_normalize(
        RawDataset(frame, import_options),
        map_columns(frame, {}),
        import_options,
    )

    assert result.valid is False
    assert {issue.field for issue in result.errors} >= {'refund_amount', 'cost_amount', 'quantity'}
    codes = {issue.code for issue in result.errors}
    assert 'invalid_refund_amount' in codes
    assert 'negative_cost_amount' in codes
    assert 'negative_quantity' in codes


def test_validation_preserves_high_precision_money_without_rejecting_it() -> None:
    from decimal import Decimal
    from data_sources.mapper import map_columns
    from data_sources.validator import validate_and_normalize
    from models.sales import RawDataset

    frame = pd.DataFrame([{
        'order_date': '2024-01-01',
        'sales_amount': '242571.6145',
        'refund_amount': '0.0007',
        'cost_amount': '167676.95125',
    }])
    import_options = options(grain='order_line')
    normalized, result = validate_and_normalize(
        RawDataset(frame, import_options), map_columns(frame, {}), import_options,
    )

    assert result.valid is True, result.errors
    assert normalized.loc[0, 'sales_amount'] == Decimal('242571.6145')
    assert normalized.loc[0, 'refund_amount'] == Decimal('0.0007')
    assert normalized.loc[0, 'cost_amount'] == Decimal('167676.95125')


def test_validation_marks_all_null_optional_amount_columns_unavailable(tmp_path: Path) -> None:
    from data_sources.csv_source import load_csv
    from data_sources.mapper import map_columns
    from data_sources.validator import validate_and_normalize

    source = tmp_path / "empty_optional_amounts.csv"
    source.write_text(
        "order_date,sales_amount,refund_amount,cost_amount\n2024-01-01,100,,\n",
        encoding="utf-8",
    )
    options = ImportOptions(
        source_name=source.name,
        grain="order_line",
        currency="USD",
    )
    raw = load_csv(source, options)

    _, result = validate_and_normalize(raw, map_columns(raw.df, {}), options)

    assert result.valid is True
    assert result.profile is not None
    assert "net_sales" in result.profile.unavailable_metrics
    assert "gross_profit" in result.profile.unavailable_metrics
    assert "gross_margin" in result.profile.unavailable_metrics


def test_dataset_store_round_trip_preserves_decimal_money(tmp_path: Path) -> None:
    from decimal import Decimal
    from storage.datasets import DatasetStore
    from models.sales import DatasetProfile

    store = DatasetStore(tmp_path)
    profile = DatasetProfile(
        dataset_id="ds-test", session_id="session-a", rows=1,
        columns=["order_date", "sales_amount"], grain="aggregate", currency="USD",
        min_date=None, max_date=None, available_metrics=["sales"], unavailable_metrics={},
    )
    store.save("session-a", pd.DataFrame({"order_date": ["2024-01-01"], "sales_amount": [Decimal("242571.6145")]}), profile)
    loaded = store.load("session-a", next(tmp_path.glob("session-a/ds_*")).name)
    assert Decimal(loaded.loc[0, "sales_amount"]) == Decimal("242571.6145")
