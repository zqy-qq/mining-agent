"""DeepSeek 接入：OpenAI SDK + base_url，关闭深度思考。

⚠️ 实现约束：带 tools 参数时，每轮的 reasoning_content 必须完整回传，
否则 API 返回 400。LangGraph 编排中由 MessagesState 的 add_messages 归约器
自动处理。
"""
from __future__ import annotations
import json
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from shared.config import (
    DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL,
    DEEPSEEK_TEMPERATURE, DEEPSEEK_MAX_TOKENS, require_api_key,
)
from shared.utils import get_logger

logger = get_logger("agent.llm")


def get_llm(tools: list | None = None) -> ChatOpenAI:
    """构造 ChatOpenAI 实例（指向 DeepSeek）。"""
    require_api_key()
    llm = ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=DEEPSEEK_TEMPERATURE,
        max_tokens=DEEPSEEK_MAX_TOKENS,
    ).bind(extra_body={"thinking": {"type": "disabled"}})
    if tools:
        llm = llm.bind_tools(tools)
    return llm


def to_openai_tools(tools: list) -> list[dict[str, Any]]:
    """LangChain Tool 列表 → OpenAI tools schema。"""
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.args_schema.model_json_schema() if t.args_schema else {
                    "type": "object", "properties": {}
                },
            },
        })
    return out


SYSTEM_PROMPT = """你是矿权日报 Agent。请严格按以下步骤生成日报：

1. 第 1 轮：一次发全 3 个入口工具的 tool_calls（并行）：
   - search(query=<矿区名>+<矿种>，中文即可，如"海博 铜矿", days=7) → 新闻列表
     （新闻工具内部会把矿区/矿种转成英文检索词，去英文矿业媒体查，中文查询无需翻译）
   - extract_resources(pdf_url=<实体归一结果里给出的报告文件名>) → 储量数据
   - get_trend(commodity=<实体归一结果里的价格品种>, days=30) → 30 天价格走势

2. 第 2 轮（可选）：仅当确实需要某条新闻全文时，才调 fetch_article(url)。

3. 工具调用纪律（必须遵守，否则任务失败）：
   - 最多 2 轮工具调用。第 2 轮结束后，无论信息是否完整都必须直接输出简报。
   - 工具返回空列表或 error 时，不要重试、不要换关键词反复试。视为该数据源不可用。
   - 缺数据的分段如实写"该数据源暂不可用"，绝不编造数字。
   - 【零容忍】新闻段若 search 返回 count=0：必须原样写"本期未检索到有效新闻"，
     可附上检索词。**严禁**基于"公开项目背景""行业常识""历史印象"编造任何新闻条目、
     要点提示、标题或来源链接。宁可整段只有一句话，也不许编。

4. 直接从 `# 标题` 开始输出 4 段简报（中文，800~1500 字）。
   **禁止输出任何前言、思考过程或元说明**（如"数据都已返回""我将如何处理""The news results are off-topic"），
   报告正文第一行必须是 Markdown 标题：
   - 【新闻摘要】3 条要点，带引用标记 [1][2][3]；无结果时如实写"本期未检索到有效新闻"，不得编造
   - 【储量数据】表格：Measured / Indicated / Inferred / Reserve
   - 【价格走势】近 30 天趋势 + 涨跌幅
   - 【风险提示】3 条具体风险，每条必须挂数据（价格/储量/新闻）

引用编号在文末统一列出对应链接。
"""


__all__ = ["get_llm", "to_openai_tools", "SYSTEM_PROMPT",
           "HumanMessage", "SystemMessage", "AIMessage", "ToolMessage"]
