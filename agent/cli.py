"""CLI 入口：命令行跑图 + 存档。

用法：
    python -m agent.cli "给我萨克帕斯锂矿日报"
    python -m agent.cli --mine thacker-pass --days 7
"""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

from agent.graph import run
from agent.mcp_client import get_tools
from shared.config import OUTPUT_DIR
from shared.utils import get_logger, today_str

logger = get_logger("agent.cli")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="矿权日报 Agent CLI")
    p.add_argument("query", nargs="*", help="用户查询文本")
    p.add_argument("--mine", help="矿区 key（pilbara/thacker-pass/haib）")
    p.add_argument("--days", type=int, default=7, help="新闻时间窗口（天）")
    p.add_argument("--out", help="输出文件路径（默认 output/YYYY-MM-DD_矿区.md）")
    return p.parse_args()


async def main() -> int:
    args = parse_args()

    # 构造查询
    if args.query:
        query = " ".join(args.query)
    elif args.mine:
        query = f"给我{args.mine}矿区的近{args.days}天日报"
    else:
        print("用法: python -m agent.cli <query> 或 --mine <key>")
        return 1

    print(f"[1/3] 加载 MCP 工具...")
    tools = await get_tools()

    print(f"[2/3] 跑图生成日报...")
    report_text = await run(query, tools)

    if not report_text:
        print("[!] 未生成报告")
        return 1

    print(f"\n{'='*60}\n{report_text}\n{'='*60}")

    # 存档
    out_path = Path(args.out) if args.out else OUTPUT_DIR / f"{today_str()}_{args.mine or 'auto'}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_text, encoding="utf-8")
    print(f"\n[3/3] 已存档 → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
