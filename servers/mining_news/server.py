"""mining-news MCP server：新闻聚合（RSS 搜索 + 全文抓取）。

数据源（按可用性降级）：
1. mining.com 关键词搜索 RSS —— 主源，按关键词精准检索（英文矿业专业媒体）
2. mining.com 固定 feed —— 备源，拉最新列表后本地过滤
3. Nasdaq 商品新闻 RSS —— 兜底

中文查询会自动转成英文检索词（矿区别名 + 矿种词表），因为可用的矿业新闻源
都是英文媒体。Google News / Bing News 在当前网络下不可达或已停止提供 RSS。
"""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx
from fastmcp import FastMCP

from shared.config import load_report_index
from shared.utils import get_logger

logger = get_logger("mining-news")

mcp = FastMCP("mining-news")

# 矿种中文 -> 英文检索词
COMMODITY_EN = {
    "lithium": ["锂", "锂矿", "锂辉石", "碳酸锂", "lithium", "spodumene"],
    "copper": ["铜", "铜矿", "阴极铜", "copper"],
    "cobalt": ["钴", "钴矿", "cobalt"],
    "nickel": ["镍", "镍矿", "nickel"],
    "gold": ["金", "金矿", "gold"],
}

# RSS 源：search 型直接用返回结果；feed 型需本地关键词过滤
RSS_SOURCES = [
    # 1. mining.com 关键词搜索（主源，服务端已按关键词过滤）
    ("search", "https://www.mining.com/?s={query}&feed=rss2"),
    # 2. mining.com 最新 feed（备源，本地过滤）
    ("feed", "https://www.mining.com/feed/"),
    # 3. Nasdaq 商品新闻（兜底，本地过滤）
    ("feed", "https://www.nasdaq.com/feed/rssoutbound?category=Commodities"),
]
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# 抓全文时的简单清洗：去掉 script/style
_CLEAN_RE = re.compile(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)


def _english_terms(query: str) -> list[str]:
    """把中文查询里的矿区 / 矿种转成英文检索词。

    矿区：读 report_index.json 的 aliases，命中中文别名后取该矿区的 ASCII 英文名。
    矿种：查 COMMODITY_EN 词表。
    """
    ql = query.lower()
    terms: list[str] = []

    try:
        for key, meta in load_report_index().items():
            aliases = list(meta.get("aliases") or []) + [key, meta.get("name_cn", "")]
            if any(a and a.lower() in ql for a in aliases):
                en = next((a for a in [key] + aliases if a and a.isascii()), key)
                terms.append(en)
    except Exception as e:  # 索引读取失败不影响搜索
        logger.warning(f"entity lookup failed: {e}")

    for en, words in COMMODITY_EN.items():
        if any(w.lower() in ql for w in words):
            terms.append(en)

    return terms


def _candidate_queries(query: str) -> list[str]:
    """构造检索词候选：英文组合 → 单个英文词 → 原始查询。"""
    terms = _english_terms(query)
    out: list[str] = []
    if terms:
        out.append(" ".join(terms))
        out.extend(terms)
    out.append(query)
    seen, res = set(), []
    for q in out:
        k = q.strip().lower()
        if k and k not in seen:
            seen.add(k)
            res.append(q.strip())
    return res


def _parse_rss(xml_text: str) -> list[dict[str, Any]]:
    """解析 RSS XML -> [{title, url, source, published}]。"""
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else "mining.com"
        if title and link:
            items.append({"title": title, "url": link, "source": source, "published": pub})
    return items


def _filter_by_terms(items: list[dict[str, Any]], terms: list[str]) -> list[dict[str, Any]]:
    """保留标题或来源里出现任一检索词的条目（大小写不敏感）。"""
    if not terms:
        return items
    keys = [t.lower() for t in terms if t]
    return [it for it in items if any(k in (it["title"] + " " + it["source"]).lower() for k in keys)]


def _within_days(items: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """按发布时间做软过滤：窗口内有结果就用窗口内的，否则回退全部。"""
    if days <= 0:
        return items
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    for it in items:
        try:
            dt = datetime.strptime(it["published"], "%a, %d %b %Y %H:%M:%S %z")
        except Exception:
            continue
        if dt >= cutoff:
            recent.append(it)
    return recent or items


@mcp.tool()
async def search(query: str, days: int = 7) -> dict[str, Any]:
    """按关键词与时间窗口检索矿业新闻。

    支持中文查询：内部会自动把矿区中文名（如「海博」）与矿种（如「铜矿」）
    转成英文检索词，再到英文矿业媒体检索。

    Args:
        query: 搜索关键词（如 "海博 铜矿" / "Pilbara lithium"）。
        days: 时间窗口（天数，默认 7；窗口内无结果时回退为最近条目）。

    Returns:
        {"query", "count", "items": [{title, url, source, published}]}。
        失败返回 count=0 且带 error 字段。
    """
    candidates = _candidate_queries(query)
    terms = _english_terms(query)
    last_error = ""

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for q in candidates:
            for kind, tpl in RSS_SOURCES:
                url = tpl.format(query=quote_plus(q))
                try:
                    resp = await client.get(url, headers={"User-Agent": USER_AGENT})
                    resp.raise_for_status()
                    items = _parse_rss(resp.text)
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e}"
                    logger.warning(f"source {url[:60]} failed: {last_error}")
                    continue

                # search 型源服务端已按关键词过滤，不再本地过滤；feed 型需要过滤
                if kind == "feed":
                    items = _filter_by_terms(items, terms or [q])
                items = _within_days(items, days)[:20]

                if not items:
                    last_error = f"{url[:60]} -> 0 rows"
                    logger.warning(f"source {url[:60]} -> 0 rows (q={q!r}), trying next")
                    continue

                logger.info(f"search({query!r}) -> q={q!r} via {url[:45]} -> {len(items)} rows")
                return {"query": query, "resolved_query": q, "days": days,
                        "count": len(items), "items": items}

    logger.error(f"all sources failed, last={last_error}")
    return {"query": query, "days": days, "count": 0, "items": [], "error": last_error}


@mcp.tool()
async def fetch_article(url: str) -> dict[str, Any]:
    """抓取指定新闻正文，返回清洗后的纯文本。

    Args:
        url: 新闻详情页 URL（search() 返回的 url）。

    Returns:
        {"title": ..., "text": "...", "url": ...}。失败时 text 为空。
    """
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
        html = resp.text
        # 极简正文抽取：去 script/style，再去标签
        html = _CLEAN_RE.sub("", html)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else ""
        if len(text) < 200:
            # 内容过短 = 抽取失败（页面可能需要 JS 渲染）
            # 显式报错，避免模型以为拿到了正文而反复重试
            logger.warning(f"fetch_article too short ({len(text)} chars)")
            return {"title": title, "text": "", "url": url,
                    "error": "content too short (page may require JS rendering)"}
        logger.info(f"fetch_article({url[:60]}...) -> {len(text)} chars")
        return {"title": title, "text": text[:3000], "url": url}
    except Exception as e:
        logger.error(f"fetch_article failed: {e}")
        return {"title": "", "text": "", "url": url, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
