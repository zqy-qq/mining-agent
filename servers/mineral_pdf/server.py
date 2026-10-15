"""mineral-pdf MCP server：矿权报告资源量抽取（索引 + 预抽数据）。

## 设计取舍（面试重点）

真实 NI 43-101 / JORC 报告的储量表版式差异极大：
- 单位可能写在行内（`Indicated 180.1 Mt @ 1.49% Li2O`），也可能只在表头（`Tonnes (Mt)`）
- 同一分类重复出现（In-situ / Stockpiles / 合计）
- 大量扫描件、跨页表、脚注穿插

用正则/表格解析硬抽，**准确率不可控且会静默出错**（实测把 Thacker Pass 的
266.2 Mt 抽成 1.78 Mt）。给 Agent 喂错误数据比不给数据危险得多。

因此本 server 默认使用 `data/report_index.json` 里的**人工核对过的预抽数据**，
真抽（pdfplumber）作为**可选实验特性**，需要显式开启：

    set ENABLE_PDF_EXTRACT=1        # Windows
    export ENABLE_PDF_EXTRACT=1     # macOS/Linux

开启后若抽到结果会优先返回（`source: "pdf"`），抽不到自动回退（`source: "fallback"`）。
"""
from __future__ import annotations
import os
import re
import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from shared.config import REPORT_INDEX_PATH, REPORTS_DIR
from shared.utils import get_logger

logger = get_logger("mineral-pdf")

mcp = FastMCP("mineral-pdf")

# NI 43-101 / JORC 标准资源量分类
RESOURCE_CATEGORIES = ["Measured", "Indicated", "Inferred", "Reserve"]

# 真抽开关：默认关闭（原因见模块 docstring）
ENABLE_PDF_EXTRACT = os.getenv("ENABLE_PDF_EXTRACT", "0") == "1"


def _load_index() -> dict:
    if not REPORT_INDEX_PATH.exists():
        return {}
    try:
        with open(REPORT_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"load report_index failed: {e}")
        return {}


def _find_report(pdf_url: str) -> tuple[str, dict, dict]:
    """在 report_index.json 里定位一份报告。

    返回 (mine_key, mine, report)，找不到返回 ("", {}, {})。
    """
    target = Path(pdf_url).name
    for mine_key, mine in _load_index().items():
        if not isinstance(mine, dict):
            continue
        for r in mine.get("reports", []):
            if (
                r.get("url") == pdf_url
                or r.get("source_page") == pdf_url
                or Path(r.get("local_path", "")).name == target
            ):
                return mine_key, mine, r
    return "", {}, {}


def _extract_from_pdf(pdf_path: Path, hint_page: int = -1) -> list[dict[str, Any]]:
    """从 PDF 中抽资源量表（实验特性，默认不启用）。

    能吃下两种常见版式：
      1) 单位在行内：Indicated: 180.1 Mt @ 1.49% Li2O
      2) 单位在表头：Indicated  354  1.28  120  0.62

    同一分类重复出现时取**最后一个**匹配（合计行通常排最后）。抽不到返回空列表，
    由调用方回退 fallback。
    """
    import pdfplumber

    def scan(text: str, page_num: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for cat in RESOURCE_CATEGORIES:
            pat = (
                rf"\b{cat}\b[^\n]{{0,24}}?"
                rf"([\d][\d,]*(?:\.\d+)?)\s*(?:[Mm]t\b)?"
                rf"[^\n\d]{{0,12}}?([\d.]+)"
            )
            found = None
            for tonnes, grade in re.findall(pat, text, re.IGNORECASE):
                try:
                    t_val = float(tonnes.replace(",", ""))
                    g_val = float(grade)
                except ValueError:
                    continue
                # 合理性校验：吨位 1~100000 Mt，品位 0.001~50%
                if 1 <= t_val <= 100000 and 0.001 <= g_val <= 50:
                    found = (tonnes, grade)
            if found:
                out.append({
                    "category": cat,
                    "tonnes": f"{found[0]} Mt",
                    "grade": f"{found[1]}%",
                    "source_page": page_num,
                })
        return out

    items: list[dict[str, Any]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = pdf.pages
        n = len(pages)
        order = list(range(1, n + 1))
        if 1 <= hint_page <= n:
            near = list(range(max(1, hint_page - 2), min(n, hint_page + 2) + 1))
            order = near + [i for i in order if i not in near]

        for page_num in order:
            try:
                text = pages[page_num - 1].extract_text() or ""
            except Exception:
                continue
            for it in scan(text, page_num):
                if not any(x["category"] == it["category"] for x in items):
                    items.append(it)
            if len(items) >= len(RESOURCE_CATEGORIES):
                break

    return items


def _extract_from_fallback(pdf_url: str) -> dict[str, Any]:
    """从 report_index.json 的 fallback 字段读取预抽数据（默认路径）。"""
    mine_key, mine, report = _find_report(pdf_url)
    if not report:
        return {"source": "fallback", "items": [],
                "warning": f"未找到 {pdf_url} 对应的报告索引"}

    fb = mine.get("fallback", {})
    items = []
    for cat in RESOURCE_CATEGORIES:
        if cat not in fb:
            continue
        val = fb[cat]
        m = re.match(r"([\d.,]+\s*[MmKk]t)\s*@\s*([\d.]+%\s*\w+)", val)
        if m:
            items.append({
                "category": cat,
                "tonnes": m.group(1).strip(),
                "grade": m.group(2).strip(),
                "source_page": report.get("hint_resource_table_page", -1),
            })
        else:
            items.append({
                "category": cat,
                "tonnes": val,
                "grade": "",
                "source_page": report.get("hint_resource_table_page", -1),
            })

    return {
        "source": "fallback",
        "items": items,
        "fallback_raw": fb,
        "report_title": report.get("title"),
        "mine_key": mine_key,
    }


@mcp.tool()
async def extract_resources(pdf_url: str) -> dict[str, Any]:
    """抽取 NI 43-101 / JORC 报告中的资源量数据。

    数据来源策略：
    - 路径 A（实验，默认关闭）：data/reports/ 下有同名 PDF 且 ENABLE_PDF_EXTRACT=1
      → pdfplumber 真抽，抽到才用
    - 路径 B（默认）：读 report_index.json 中人工核对过的 fallback 预抽数据

    Args:
        pdf_url: PDF 的文件名（如 "thacker-pass-ni43-101.pdf"）。

    Returns:
        {"source": "pdf"|"fallback", "items": [{"category","tonnes","grade","source_page"}], ...}
    """
    local_path = REPORTS_DIR / Path(pdf_url).name
    _, _, report = _find_report(pdf_url)
    hint_page = int(report.get("hint_resource_table_page", -1) or -1)

    # 路径 A：本地真抽（实验特性，默认关闭）
    if ENABLE_PDF_EXTRACT and local_path.exists():
        try:
            items = _extract_from_pdf(local_path, hint_page=hint_page)
            if items:
                logger.info(f"extract_resources({pdf_url}) -> pdf extract {len(items)} rows")
                return {"source": "pdf", "items": items, "report_title": local_path.stem}
            # 抽到 0 条必须回退，否则 agent 会拿到空储量表
            logger.warning(f"extract_resources({pdf_url}) -> pdf 0 rows, fallback")
        except Exception as e:
            logger.error(f"PDF extract failed: {e}, fallback")

    # 路径 B：fallback 预抽数据（默认）
    result = _extract_from_fallback(pdf_url)
    logger.info(f"extract_resources({pdf_url}) -> fallback ({len(result.get('items', []))} rows)")
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
