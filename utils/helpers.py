"""
工具函数辅助模块：汇率转换、翻译等通用辅助函数
"""

import os
import sys
import json

# 汇率表（与 tools.py 中的保持一致）
EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "JPY": 149.50,
    "CNY": 7.24,
    "KRW": 1320.0,
}


def convert_currency(amount: float, from_currency: str, to_currency: str) -> float:
    """
    简单的汇率转换函数。
    可扩展点：对接实时汇率 API（如 exchangerate-api.com / fixer.io）
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency not in EXCHANGE_RATES or to_currency not in EXCHANGE_RATES:
        raise ValueError(f"不支持的货币类型: {from_currency} 或 {to_currency}")

    amount_in_usd = amount / EXCHANGE_RATES[from_currency]
    return round(amount_in_usd * EXCHANGE_RATES[to_currency], 2)


def get_supported_currencies() -> list:
    """返回支持的货币列表"""
    return list(EXCHANGE_RATES.keys())


def format_price(amount: float, currency: str = "USD") -> str:
    """格式化价格显示"""
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "KRW": "₩"}
    symbol = symbols.get(currency, currency + " ")
    if currency in ("JPY", "KRW"):
        return f"{symbol}{int(amount):,}"
    return f"{symbol}{amount:,.2f}"
