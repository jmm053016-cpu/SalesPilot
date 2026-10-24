"""集中管理报告图表的配色、字体与格式化规则。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

# 防御性设置：即使有人绕过 charts/__init__.py 直接导入本模块，也保证无界面后端。
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams


def configure_chinese_font() -> str:
    """Configure a usable font without leaking Matplotlib global state beyond rcParams."""
    candidates = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Source Han Sans CN",
        "DejaVu Sans",
    ]
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            rcParams["font.sans-serif"] = [name]
            rcParams["axes.unicode_minus"] = False
            return name
    raise RuntimeError("Chinese font is unavailable")


def apply_style() -> None:
    configure_chinese_font()
    rcParams["figure.dpi"] = 120
    rcParams["savefig.bbox"] = "tight"
    rcParams["axes.grid"] = True
    rcParams["grid.alpha"] = 0.25


def save_figure(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format="png")
    plt.close(fig)
