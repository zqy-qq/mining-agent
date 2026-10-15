"""lme-price 真实行情源：新浪财经公开接口（免费、无需 key）。

四个入口：

| 用途 | 接口 |
|---|---|
| LME 外盘快照 | `https://hq.sinajs.cn/list=hf_CAD` |
| LME 外盘日K | `.../GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=CAD` |
| 广期所内盘快照 | `https://hq.sinajs.cn/list=nf_LC0` |
| 广期所内盘日K | `.../InnerFuturesNewService.getDailyKLine?symbol=LC0` |

品种映射见 `COMMODITY_SOURCES`：
- `market="lme"` → 新浪外盘，**美元/吨**（CAD 铜 / NID 镍 / AHD 铝 / ZSD 锌 / SND 锡 / PBD 铅）
- `market="gfex"` → 新浪内盘，**人民币元/吨**（LC0 碳酸锂，广期所）

未列出的品种（如 `spodumene` 锂辉石、`cobalt` 钴）国内外均无对应期货合约，
`resolve()` 返回 `None`，由调用方降级到内置基准价并如实标注。

任一请求失败均返回 `None`（不抛异常），保证 Agent 主流程不被行情源拖断。

## 两个必踩的坑（已在代码中处理）

1. 新浪响应体是 **GBK**，必须 `content.decode("gbk")`，否则中文品种名乱码。
2. 新浪内盘期货代码**必须带 `nf_` 前缀**。漏掉前缀不会报错，而是 HTTP 200 返回
   **约两年前的陈旧数据**（实测 `list=CU0` 返回 2024-07-17 的报价）。
   因此 `fetch_latest()` 会校验返回日期，陈旧则视为失败。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import httpx

from shared.utils import get_logger

logger = get_logger("lme-price.sources")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn",
}
_TIMEOUT = httpx.Timeout(10.0, connect=6.0)

# 行情陈旧判定阈值（自然日）。超过则判定为「拿到了不复新的数据」→ 降级
_STALE_DAYS = 15

# 品种 → 真实源映射
COMMODITY_SOURCES: dict[str, dict[str, str]] = {
    # --- LME 外盘（美元/吨）---
    "copper":            {"market": "lme", "symbol": "CAD", "name": "LME 伦铜", "unit": "USD/t", "currency": "USD"},
    "copper-cathode":    {"market": "lme", "symbol": "CAD", "name": "LME 伦铜", "unit": "USD/t", "currency": "USD"},
    "nickel":            {"market": "lme", "symbol": "NID", "name": "LME 伦镍", "unit": "USD/t", "currency": "USD"},
    "aluminium":         {"market": "lme", "symbol": "AHD", "name": "LME 伦铝", "unit": "USD/t", "currency": "USD"},
    "aluminum":          {"market": "lme", "symbol": "AHD", "name": "LME 伦铝", "unit": "USD/t", "currency": "USD"},
    "zinc":              {"market": "lme", "symbol": "ZSD", "name": "LME 伦锌", "unit": "USD/t", "currency": "USD"},
    "tin":               {"market": "lme", "symbol": "SND", "name": "LME 伦锡", "unit": "USD/t", "currency": "USD"},
    "lead":              {"market": "lme", "symbol": "PBD", "name": "LME 伦铅", "unit": "USD/t", "currency": "USD"},
    # --- 广期所内盘（人民币元/吨）---
    "lithium":           {"market": "gfex", "symbol": "LC0", "name": "广期所碳酸锂", "unit": "CNY/t", "currency": "CNY"},
    "lithium-carbonate": {"market": "gfex", "symbol": "LC0", "name": "广期所碳酸锂", "unit": "CNY/t", "currency": "CNY"},
    "carbonate":         {"market": "gfex", "symbol": "LC0", "name": "广期所碳酸锂", "unit": "CNY/t", "currency": "CNY"},
    # 无期货合约：spodumene（锂辉石）/ cobalt（钴）需降级到内置基准价
}

_SNAPSHOT_RE = re.compile(r'hq_str_([A-Za-z0-9_]+)="([^"]*)"')
_JSONP_RE = re.compile(r"\((\[.*\])\)", re.S)


def resolve(commodity: str) -> dict[str, str] | None:
    """品种名 → 真实源描述，未覆盖返回 None。"""
    return COMMODITY_SOURCES.get((commodity or "").strip().lower())


def supported_commodities() -> list[str]:
    return sorted(COMMODITY_SOURCES)


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """带 1 次重试的 GET，失败返回 None。"""
    for attempt in (1, 2):
        try:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code == 200:
                return resp
            logger.warning(f"attempt {attempt}: {url} -> HTTP {resp.status_code}")
        except Exception as e:  # noqa: BLE001 — 任何网络异常都走降级
            logger.warning(f"attempt {attempt}: {url} -> {type(e).__name__}: {e}")
    return None


def _parse_snapshots(text: str) -> dict[str, list[str]]:
    """解析新浪 hq_str_XXX="a,b,c" 响应体（GBK 已解码）。"""
    out: dict[str, list[str]] = {}
    for code, body in _SNAPSHOT_RE.findall(text):
        out[code] = body.split(",") if body else []
    return out


def _parse_jsonp(text: str) -> list[dict[str, Any]] | None:
    """从 JSONP 响应里取出 JSON 数组。"""
    m = _JSONP_RE.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _is_stale(date_str: str) -> bool:
    """日期距今天超过 _STALE_DAYS 自然日 → 陈旧数据（新浪漏前缀陷阱的兜底）。"""
    try:
        d = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
    except (ValueError, AttributeError):
        return True
    return (datetime.now() - d).days > _STALE_DAYS


def _to_float(v: Any) -> float | None:
    try:
        return round(float(str(v).replace(",", "")), 2)
    except (ValueError, TypeError):
        return None


async def fetch_latest(commodity: str) -> dict[str, Any] | None:
    """取最新快照价。失败/品种无源/数据陈旧 → 返回 None。"""
    src = resolve(commodity)
    if not src:
        return None

    code = f"hf_{src['symbol']}" if src["market"] == "lme" else f"nf_{src['symbol']}"
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await _get(client, f"https://hq.sinajs.cn/list={code}")
    if resp is None:
        return None

    fields = _parse_snapshots(resp.content.decode("gbk", errors="ignore")).get(code)
    if not fields:
        return None

    # 外盘 hf_：0=最新价, 12=日期, 13=名称
    # 内盘 nf_：5=最新价, 17=日期, 0=名称
    if src["market"] == "lme":
        if len(fields) < 13:
            return None
        close_raw, date_str = fields[0], fields[12]
        display = fields[13] if len(fields) > 13 and fields[13] else src["name"]
    else:
        if len(fields) < 18:
            return None
        close_raw, date_str = fields[5], fields[17]
        display = fields[0] or src["name"]

    close = _to_float(close_raw)
    if close is None or close <= 0:
        return None
    if _is_stale(date_str):
        logger.warning(f"{code} 返回陈旧日期 {date_str}，判定不可用")
        return None

    return {
        "commodity": commodity.strip().lower(),
        "date": date_str.strip()[:10],
        "close": close,
        "unit": src["unit"],
        "currency": src["currency"],
        "source": f"sina-{src['market']}",
        "source_name": display,
    }


async def fetch_history(commodity: str, days: int = 30) -> dict[str, Any] | None:
    """取近 N 个交易日序列 + 涨跌幅。失败/品种无源 → 返回 None。"""
    src = resolve(commodity)
    if not src:
        return None

    sym = src["symbol"]
    if src["market"] == "lme":
        url = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
               f"var%20_{sym}_=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={sym}")
    else:
        url = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
               f"var%20_{sym}_=/InnerFuturesNewService.getDailyKLine?symbol={sym}")

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await _get(client, url)
    if resp is None:
        return None

    rows = _parse_jsonp(resp.content.decode("gbk", errors="ignore"))
    if not rows:
        return None

    # 外盘字段 date/close；内盘字段 d/c
    series: list[dict[str, Any]] = []
    for r in rows:
        d = r.get("date") or r.get("d")
        c = _to_float(r.get("close") if "close" in r else r.get("c"))
        if d and c is not None:
            series.append({"date": str(d)[:10], "close": c})
    if not series:
        return None

    series = series[-max(2, int(days)):]
    if _is_stale(series[-1]["date"]):
        logger.warning(f"{sym} 日K 末根日期 {series[-1]['date']} 陈旧，判定不可用")
        return None

    first, last = series[0]["close"], series[-1]["close"]
    return {
        "commodity": commodity.strip().lower(),
        "days": len(series),
        "series": series,
        "change_pct": round((last - first) / first * 100, 2) if first else 0.0,
        "latest": last,
        "unit": src["unit"],
        "currency": src["currency"],
        "source": f"sina-{src['market']}",
        "source_name": src["name"],
    }


async def fetch_usdcny() -> float | None:
    """在岸美元人民币汇率（用于人民币↔美元换算），失败返回 None。"""
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await _get(client, "https://hq.sinajs.cn/list=USDCNY")
    if resp is None:
        return None
    fields = _parse_snapshots(resp.content.decode("gbk", errors="ignore")).get("USDCNY")
    if not fields or len(fields) < 2:
        return None
    return _to_float(fields[1])


__all__ = [
    "COMMODITY_SOURCES", "resolve", "supported_commodities",
    "fetch_latest", "fetch_history", "fetch_usdcny",
]
