"""从受支持的数据源读取记录，不接受调用方拼接的任意 SQL。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

import pandas as pd

from models.sales import ImportOptions, RawDataset

from .schema import MAX_ROWS

_ALLOWED_QUERIES: dict[str, str] = {
    'orders': 'SELECT * FROM orders',
}


def load_sqlite(db_path: Path, query_name: Literal['orders']) -> RawDataset:
    if query_name not in _ALLOWED_QUERIES:
        raise ValueError(f'unsupported query name: {query_name}')
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    with sqlite3.connect(db_path) as connection:
        frame = pd.read_sql_query(_ALLOWED_QUERIES[query_name], connection)
    if len(frame) > MAX_ROWS:
        raise ValueError('row count exceeds 100,000 limit')
    options = ImportOptions(source_name=db_path.name, grain='order', currency=None)
    return RawDataset(frame, options)
