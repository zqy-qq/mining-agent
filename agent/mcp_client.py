"""MCP 客户端：连接 3 个 server + 工具发现。

基于 langchain-mcp-adapters 的 MultiServerMCPClient。

两个 Windows 必踩的坑，这里都处理了：
1. command 必须用 sys.executable —— PATH 里的 python 可能指向别的环境，
   会导致子进程 ModuleNotFoundError。
2. env 必须显式指定 UTF-8 —— Windows 子进程默认用 cp936(GBK) 编解码 stdio，
   中文参数（如 query="锂矿 皮尔巴拉"）会在 JSON-RPC 上变成乱码。
"""
from __future__ import annotations
import os
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient

from shared.config import ROOT
from shared.utils import get_logger

logger = get_logger("agent.mcp_client")

# 继承当前环境 + 强制 UTF-8（否则 Windows 子进程 stdio 用 GBK，中文乱码）
_CHILD_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}


def _server(module: str) -> dict:
    """构造单个 stdio server 配置。"""
    return {
        "command": sys.executable,  # 当前解释器，避免 PATH 指向别的环境
        "args": ["-X", "utf8", "-m", module],
        "transport": "stdio",
        "cwd": str(ROOT),
        "env": _CHILD_ENV,
    }


def make_mcp_client() -> MultiServerMCPClient:
    """构造 MultiServerMCPClient，配置 3 个 server（stdio 传输）。"""
    return MultiServerMCPClient({
        "mining-news": _server("servers.mining_news.server"),
        "mineral-pdf": _server("servers.mineral_pdf.server"),
        "lme-price": _server("servers.lme_price.server"),
    })


async def get_tools() -> list:
    """异步获取 3 个 server 注册的全部工具。"""
    client = make_mcp_client()
    tools = await client.get_tools()
    logger.info(f"已加载 {len(tools)} 个工具: {[t.name for t in tools]}")
    return tools
