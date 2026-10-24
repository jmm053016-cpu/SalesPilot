"""读取 CSV 销售文件，并保留后续字段映射与校验所需信息。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from models.sales import ImportOptions, RawDataset

from .schema import MAX_ROWS, check_source_limits


def load_csv(path: Path, options: ImportOptions) -> RawDataset:
    path = Path(path)
    check_source_limits(path)
    frame = pd.read_csv(path, encoding='utf-8-sig', dtype=str)
    if len(frame) > MAX_ROWS:
        raise ValueError('row count exceeds 100,000 limit')
    return RawDataset(frame, options)
