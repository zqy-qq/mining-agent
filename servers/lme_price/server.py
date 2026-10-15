"""lme-price MCP server：价格行情（mock 数据）。

数据源策略：本项目用 mock 数据（基于 LME 公开页面 2026-09 快照）。
接 metals.dev / Yahoo Finance 只需替换 _MOCK_PRICES 字典 + 加 httpx 调用。
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta
from typing import Any

from fastmcp import FastMCP

from shared.utils import get_logger

logger = get_logger("lme-price")

mcp = FastMCP("lme-price")

# 品种 → 基础价（USD/吨，2026-09 LME 公开页面快照）
_BASE_PRICES = {
    "lithium":       18500.0,    # 碳酸锂
    "lithium-carbonate": 18500.0,
    "spodumene":     2400.0,     # 锂辉石（6% Li2O）
    "spodumene-6":   2400.0,
    "copper":        9200.0,     # 阴极铜
    "copper-cathode": 9200.0,
    "cobalt":        28500.0,    # 钴
    "nickel":        17500.0,    # 镍
}


def _generate_series(commodity: str, days: int, end_date: str | None = None) -> list[dict[str, Any]]:
    """生成 mock 时间序列（带轻微随机波动）。"""
    key = commodity.lower()
    base = _BASE_PRICES.get(key, 1000.0)
    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            end = datetime.now()
    else:
        end = datetime.now()

    # 用日期作种子，让结果可重现
    seed = int(end.strftime("%Y%m%d"))
    rng = random.Random(seed + hash(key) % 10000)

    series = []
    price = base * (1 + rng.uniform(-0.05, 0.05))
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        # 每日 ±2% 波动
        price *= (1 + rng.uniform(-0.02, 0.02))
        series.append({
            "date": d.strftime("%Y-%m-%d"),
            "close": round(price, 2),
            "commodity": key,
        })
    return series


@mcp.tool()
async def get_price(commodity: str, date: str | None = None) -> dict[str, Any]:
    """查询指定品种在指定日期的价格。

    Args:
        commodity: 品种名（如 "lithium" / "copper"）。
        date: 日期（YYYY-MM-DD，默认今天）。

    Returns:
        {"commodity", "date", "close"}。
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    series = _generate_series(commodity, days=1, end_date=date)
    logger.info(f"get_price({commodity}, {date}) -> {series[-1]['close']}")
    return series[-1] if series else {"error": "no data"}


@mcp.tool()
async def get_trend(commodity: str, days: int = 30) -> dict[str, Any]:
    """返回指定品种近 N 天的价格序列与涨跌幅。

    Args:
        commodity: 品种名（如 "lithium" / "copper"）。
        days: 天数（默认 30）。

    Returns:
        {"commodity", "days", "series": [{"date", "close"}], "change_pct": 涨跌幅%}
    """
    series = _generate_series(commodity, days=days)
    first = series[0]["close"] if series else 0
    last = series[-1]["close"] if series else 0
    change_pct = round((last - first) / first * 100, 2) if first else 0
    logger.info(f"get_trend({commodity}, {days}) -> {len(series)} rows")
    return {
        "commodity": commodity.lower(),
        "days": days,
        "series": [{"date": s["date"], "close": s["close"]} for s in series],
        "change_pct": change_pct,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
