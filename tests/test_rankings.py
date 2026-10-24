from datetime import date
from decimal import Decimal

import pandas as pd

from analytics.rankings import rank_dimension
from models.sales import DateRange


def test_rank_dimension_uses_metric_specific_amounts():
    frame = pd.DataFrame([
        {"order_date": "2024-01-01", "category": "A", "sales_amount": "100.00", "refund_amount": "80.00", "cost_amount": "10.00", "quantity": "1"},
        {"order_date": "2024-01-02", "category": "B", "sales_amount": "90.00", "refund_amount": "0.00", "cost_amount": "1.00", "quantity": "1"},
    ])
    period = DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))

    net_sales = rank_dimension(frame, period, "category", "net_sales")
    gross_profit = rank_dimension(frame, period, "category", "gross_profit")

    assert [item["dimension"] for item in net_sales.items] == ["B", "A"]
    assert [item["value"].value for item in net_sales.items] == [Decimal("90.00"), Decimal("20.00")]
    assert [item["dimension"] for item in gross_profit.items] == ["B", "A"]
    assert [item["value"].value for item in gross_profit.items] == [Decimal("89.00"), Decimal("10.00")]

def test_rank_dimension_derives_derived_metrics_from_canonical_amount_fields() -> None:
    frame = pd.DataFrame([
        {
            "order_date": "2024-01-01",
            "category": "A",
            "sales_amount": "100.00",
            "refund_amount": "80.00",
            "cost_amount": "10.00",
            "net_sales": "999.00",
            "gross_profit": "999.00",
        },
        {
            "order_date": "2024-01-02",
            "category": "B",
            "sales_amount": "90.00",
            "refund_amount": "0.00",
            "cost_amount": "1.00",
            "net_sales": "1.00",
            "gross_profit": "1.00",
        },
    ])
    period = DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31))

    net_sales = rank_dimension(frame, period, "category", "net_sales")
    gross_profit = rank_dimension(frame, period, "category", "gross_profit")

    assert [item["dimension"] for item in net_sales.items] == ["B", "A"]
    assert [item["value"].value for item in net_sales.items] == [Decimal("90.00"), Decimal("20.00")]
    assert [item["dimension"] for item in gross_profit.items] == ["B", "A"]
    assert [item["value"].value for item in gross_profit.items] == [Decimal("89.00"), Decimal("10.00")]


def test_rank_dimension_keeps_full_decimal_precision():
    frame = pd.DataFrame([
        {"order_date": "2024-01-01", "category": "A", "sales_amount": "0.0007"},
        {"order_date": "2024-01-02", "category": "A", "sales_amount": "0.0008"},
    ])
    result = rank_dimension(frame, DateRange(start=date(2024, 1, 1), end=date(2024, 1, 31)), "category", "sales")
    assert result.items[0]["value"].value == Decimal("0.0015")
