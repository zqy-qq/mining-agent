"""MCP server 启动器：仅凭本文件位置定位仓库根，不依赖 cwd / PYTHONPATH。

背景：Claude Desktop 的 mcp-config.json **不支持** `${workspaceFolder}` 变量，
也不会把 cwd 设成仓库根；直接写 `python -m servers.mining_news.server` 会
`ModuleNotFoundError: No module named 'servers'`。本脚本用 `__file__` 反推仓库根
并注入 sys.path，因此从任意 cwd、任意客户端拉起都能正常工作。

用法（写进 mcp-config.json 的 args）：
    python <仓库绝对路径>/scripts/mcp_launch.py mining-news

可用的 server 名见下面的 SERVERS 表。
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

# 名称 → 模块路径
SERVERS = {
    "mining-news": "servers.mining_news.server",
    "mineral-pdf": "servers.mineral_pdf.server",
    "lme-price": "servers.lme_price.server",
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in SERVERS:
        names = " | ".join(SERVERS)
        print(f"用法: python scripts/mcp_launch.py <{names}>", file=sys.stderr)
        return 2

    target = SERVERS[sys.argv[1]]
    root = Path(__file__).resolve().parents[1]

    # 让 `servers.*` / `shared.*` 可被导入，且 .env、data/ 的定位不受 cwd 影响
    sys.path.insert(0, str(root))
    os.chdir(root)
    # Windows 下 stdio 传输必须保证 UTF-8，否则中文经管道会乱码
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # run_name="__main__" 让模块内的 `if __name__ == "__main__": mcp.run()` 生效
    runpy.run_module(target, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
