"""图表层入口：集中导出分析结果的图表生成能力。

必须在导入任何子模块之前固定为无界面后端：本层只把图保存成 PNG 交给
报告与前端渲染，从不交互显示。若沿用环境默认后端（Windows 上是 TkAgg），
在没有交互会话或未安装 Tk 的环境（CI、容器、Debian 部署）会间歇性抛
TclError，导致图表阶段整段失败。
"""

import matplotlib

matplotlib.use("Agg")

from .chart_style import apply_style, configure_chinese_font  # noqa: E402
from .sales_charts import generate_charts  # noqa: E402

__all__ = ["apply_style", "configure_chinese_font", "generate_charts"]
