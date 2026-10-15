"""lme-price MCP server：价格行情。

## 数据源策略（真实源优先 + 降级）

1. **真实源（默认路径）**：新浪财经公开接口（免费、无需 key）
   - 铜 / 镍 / 铝 / 锌 / 锡 / 铅 → **LME 外盘**，美元/吨
   - 锂（碳酸锂）→ **广期所内盘**，人民币元/吨
   见 `sources.COMMODITY_SOURCES`。
2. **降级路径**：真实源不可用（断网 / 接口变更 / 品种无期货合约）时，
   回退到内置基准价的模拟序列，返回体 `source="fallback-mock"` 如实标注。

锂辉石（`spodumene`）与钴（`cobalt`）国内外均无对应期货合约，恒走降级路径。

降级保证「断网也能完整跑出日报」——不会因为行情源挂掉而中断 Agent 主流程。
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from fastmcp import FastMCP

from shared.utils import get_logger
from servers.lme_price import sources

logger = get_logger("lme-price")

mcp = FastMCP("lme-price")

# 降级用基准价（USD/吨，2026-09 LME 公开报价量级）
# 仅在真实源不可用时使用；返回体会标记 source="fallback-mock"
_BASE_PRICES = {
    "lithium":            18500.0,   # 碳酸锂
    "lithium-carbonate":  18500.0,
    "spodumene":          2400.0,    # 锂辉石（6% Li2O），无期货源
    "spodumene-6":        2400.0,
    "copper":             14300.0,   # 阴极铜
    "copper-cathode":     14300.0,
    "cobalt":             28500.0,   # 钴，无期货源
    "nickel":             15200.0,
}


def _mock_series(commodity: str, days: int, end_date: str | None = None) -> list[dict[str, Any]]:
    """生成降级用模拟序列（带轻微随机波动，日期做种子故可复现）。"""
    key = commodity.lower()
    base = _BASE_PRICES.get(key, 1000.0)
    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            end = datetime.now()
    else:
        end = datetime.now()

    rng = random.Random(int(end.strftime("%Y%m%d")) + hash(key) % 10000)

    series = []
    price = base * (1 + rng.uniform(-0.05, 0.05))
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        price *= (1 + rng.uniform(-0.02, 0.02))  # 每日 ±2% 波动
        series.append({
            "date": d.strftime("%Y-%m-%d"),
            "close": round(price, 2),
            "commodity": key,
        })
    return series


@mcp.tool()
async def get_price(commodity: str, date: str | None = None) -> dict[str, Any]:
    """查询指定品种的最新价格（优先真实行情，失败降级内置基准价）。

    Args:
        commodity: 品种名（如 "copper" / "lithium" / "nickel"）。
        date: 期望日期（YYYY-MM-DD），仅作参考——真实源返回的是最新报价。

    Returns:
        {"commodity", "date", "close", "unit", "currency", "source", "source_name"}
        source: "sina-lme"（LME 外盘真实价）/ "sina-gfex"（广期所真实价）
                / "fallback-mock"（内置基准模拟价）
    """
    live = await sources.fetch_latest(commodity)
    if live:
        if date:
            live["requested_date"] = date
        logger.info(f"get_price({commodity}) -> {live['close']} {live['unit']} [{live['source']}]")
        return live

    logger.warning(f"get_price({commodity}) 真实源不可用，降级内置基准价")
    series = _mock_series(commodity, days=1, end_date=date)
    row = series[-1] if series else {"date": date or "", "close": 0.0}
    return {
        "commodity": commodity.lower(),
        "date": row["date"],
        "close": row["close"],
        "unit": "USD/t",
        "currency": "USD",
        "source": "fallback-mock",
        "source_name": "内置基准价（模拟，非实时行情）",
        "warning": "真实行情源不可用，本价格为内置基准价生成的模拟值，不可用于决策",
    }


@mcp.tool()
async def get_trend(commodity: str, days: int = 30) -> dict[str, Any]:
    """返回指定品种近 N 个交易日的价格序列与涨跌幅。

    Args:
        commodity: 品种名（如 "copper" / "lithium" / "nickel"）。
        days: 天数（默认 30）。

    Returns:
        {"commodity", "days", "series": [{"date", "close"}], "change_pct",
         "unit", "currency", "source", "source_name"}
        source: "sina-lme" / "sina-gfex"（真实行情）/ "fallback-mock"（模拟）
    """
    live = await sources.fetch_history(commodity, days)
    if live:
        logger.info(f"get_trend({commodity}, {days}) -> {len(live['series'])} 根 "
                    f"[{live['source']}] {live['source_name']}")
        return live

    logger.warning(f"get_trend({commodity}) 真实源不可用，降级内置基准价")
    series = _mock_series(commodity, days=days)
    first = series[0]["close"] if series else 0
    last = series[-1]["close"] if series else 0
    return {
        "commodity": commodity.lower(),
        "days": len(series),
        "series": [{"date": s["date"], "close": s["close"]} for s in series],
        "change_pct": round((last - first) / first * 100, 2) if first else 0.0,
        "latest": last,
        "unit": "USD/t",
        "currency": "USD",
        "source": "fallback-mock",
        "source_name": "内置基准价（模拟，非实时行情）",
        "warning": "真实行情源不可用，本序列为内置基准价生成的模拟值，不可用于决策",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
