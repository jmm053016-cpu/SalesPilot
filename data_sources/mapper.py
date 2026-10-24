"""将外部列名映射为内部标准字段，供校验与分析层统一消费。"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from models.sales import ColumnMapping

DEFAULT_ALIASES: dict[str, list[str]] = {
    'order_date': ['order_date', 'date', 'create_time'],
    'sales_amount': ['sales_amount', 'amount', 'total_amount'],
    'refund_amount': ['refund_amount', 'refund'],
    'cost_amount': ['cost_amount', 'cost'],
    'quantity': ['quantity', 'qty', 'count'],
    'order_id': ['order_id', 'order_no', 'order_number'],
    'line_id': ['line_id', 'detail_id'],
    'product_id': ['product_id', 'sku'],
    'product_name': ['product_name', '商品名称'],
    'category': ['category', 'product_category'],
    'region': ['region', 'country'],
    'currency': ['currency', 'currency_code'],
    'order_status': ['order_status', 'status'],
}


def map_columns(df: pd.DataFrame, aliases: Mapping[str, list[str]]) -> ColumnMapping:
    candidates = dict(DEFAULT_ALIASES)
    candidates.update(aliases)
    mapping: dict[str, str] = {}
    normalized_columns = {str(column).strip().lower(): str(column) for column in df.columns}
    for standard_name, names in candidates.items():
        for alias in names:
            original = normalized_columns.get(alias.strip().lower())
            if original is not None:
                mapping[original] = standard_name
                break
    return ColumnMapping(mapping=mapping)
