"""销售数据源读取、字段映射与校验模块。"""

from .csv_source import load_csv
from .database_source import load_sqlite
from .excel_source import load_excel
from .mapper import map_columns
from .validator import validate_and_normalize

__all__ = ['load_csv', 'load_excel', 'load_sqlite', 'map_columns', 'validate_and_normalize']
