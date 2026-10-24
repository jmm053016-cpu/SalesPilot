from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / 'fixtures'


@pytest.fixture
def complete_sales_csv() -> Path:
    return FIXTURES_DIR / 'sales_complete.csv'



@pytest.fixture
def invalid_sales_csv() -> Path:
    return FIXTURES_DIR / 'sales_invalid.csv'
