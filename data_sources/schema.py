"""定义导入数据的标准字段、类型与业务约束。"""

from __future__ import annotations

from pathlib import Path

MAX_ROWS = 100_000
MAX_FILE_BYTES = 20 * 1024 * 1024


def check_source_limits(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('file exceeds 20 MB limit')
