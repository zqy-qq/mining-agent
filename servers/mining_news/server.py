"""mining-news MCP server：新闻聚合（RSS 搜索 + 全文抓取）。

数据源：Google News RSS（公开，无需 API key）。
"""
from __future__ import annotations
import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastmcp import FastMCP

from shared.utils import get_logger

logger = get_logger("mining-news")

mcp = FastMCP("mining-news")

# 多个新闻源（按可用性降级，空结果自动试下一个）
RSS_SOURCES = [
    # 1. Google News 中文区（中文关键词命中好）
    "https://news.google.com/rss/search?q={query}+when:{days}d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    # 2. Google News 英文区（英文关键词命中好）
    "https://news.google.com/rss/search?q={query}+when:{days}d&hl=en-US&gl=US&ceid=US:en",
    # 3. Bing News（备）
    "https://www.bing.com/news/search?q={query}&format=RSS&qft=interval%3d%228%22",
    # 4. mining.com（矿业专业媒体，固定 feed，需关键词过滤）
    "https://www.mining.com/feed/",
]
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 抓全文时的简单清洗：去掉 script/style
_CLEAN_RE = re.compile(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)


def _parse_rss(xml_text: str) -> list[dict[str, Any]]:
    """解析 RSS XML → [{title, url, source, published}]。"""
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""
        if title and link:
            items.append({
                "title": title,
                "url": link,
                "source": source,
                "published": pub,
            })
    return items


@mcp.tool()
async def search(query: str, days: int = 7) -> dict[str, Any]:
    """按关键词与时间窗口检索矿业新闻。

    Args:
        query: 搜索关键词（如 "锂矿" / "Pilbara lithium"）。
        days: 时间窗口（天数，默认 7）。

    Returns:
        {"query", "count", "items": [{title, url, source, published}]}。失败返回空 items。
    """
    # 依次尝试各源：空结果不中断，继续试下一个源
    last_error = ""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for tpl in RSS_SOURCES:
            url = tpl.format(query=query, days=days)
            try:
                resp = await client.get(url, headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                items = _parse_rss(resp.text)
                # 关键词过滤（mining.com 这类固定源需要过滤）
                if "search" not in url:
                    kw = query.lower().split()
                    items = [it for it in items if any(
                        k in (it["title"] + it.get("source", "")).lower() for k in kw
                    )]
                items = items[:20]
                if not items:
                    # ⚠️ 关键：0 条也算失败，继续降级到下一个源
                    last_error = f"{url[:50]} -> 0 rows"
                    logger.warning(f"source {url[:50]} -> 0 rows, trying next")
                    continue
                logger.info(f"search({query!r}) via {url[:40]} -> {len(items)} rows")
                return {"query": query, "days": days, "count": len(items), "items": items}
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(f"source {url[:50]} failed: {last_error}")
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
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
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
            # 内容过短 = 抽取失败（Google News 跳转页需 JS 渲染）
            # 显式报错，避免模型以为拿到了正文而反复重试
            logger.warning(f"fetch_article too short ({len(text)} chars)")
            return {"title": title, "text": "", "url": url,
                    "error": "content too short (page may require JS rendering)"}
        logger.info(f"fetch_article({url[:60]}...) -> {len(text)} chars")
        return {"title": title, "text": text, "url": url}
    except Exception as e:
        logger.error(f"fetch_article failed: {e}")
        return {"title": "", "text": "", "url": url, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
