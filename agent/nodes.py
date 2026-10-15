"""节点函数：normalize / llm_call / should_continue / report。

每个节点接收 state（MessagesState），返回增量 state。
"""
from __future__ import annotations
import json
from collections.abc import Callable
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from shared.config import load_entity_map, load_report_index, ENTITY_MAP_PATH
from shared.utils import get_logger, safe_json

logger = get_logger("agent.nodes")

# 硬止损：最多允许几轮工具调用（每轮 = 模型发一次 tool_calls）
# 正常 1~2 轮足够；设 3 是给"补一刀"留余量，同时防止模型反复重试烧 token
MAX_TOOL_ROUNDS = 3


def normalize(state: dict) -> dict:
    """实体归一节点：把用户输入的矿别名映射到标准矿区 key。

    输入：messages 最后一条 HumanMessage.content
    输出：messages 追加一条 SystemMessage（带归一化结果 + 报告索引上下文）
    """
    messages = state["messages"]
    user_msg = messages[-1].content if messages else ""
    entity_map = load_entity_map()
    report_index = load_report_index()

    # 找匹配的矿区
    matched_mine = None
    user_lower = user_msg.lower()
    for alias, key in entity_map.items():
        if alias.startswith("_"):
            continue
        if alias in user_lower:
            matched_mine = key
            break

    # 构造上下文
    ctx_lines = []
    if matched_mine and matched_mine in report_index:
        mine = report_index[matched_mine]
        ctx_lines.append(f"已识别矿区：{mine['name_cn']} ({matched_mine})")
        ctx_lines.append(f"矿种：{mine['commodity']}")
        ctx_lines.append(f"价格品种：{mine['price_symbol']}")
        ctx_lines.append(f"披露标准：{mine['disclosure_standard']}")
        ctx_lines.append(f"报告文件：{[r['local_path'].split('/')[-1] for r in mine['reports']]}")
    else:
        ctx_lines.append(f"未识别矿区。已支持：{list(report_index.keys())}")

    ctx = "\n".join(ctx_lines)
    logger.info(f"normalize: matched={matched_mine}")

    return {
        "messages": [
            SystemMessage(content=f"实体归一结果：\n{ctx}"),
        ],
        "matched_mine": matched_mine,
    }


def llm_call(state: dict, llm) -> dict:
    """调用 DeepSeek。

    关键：必须把整段 AIMessage 回传（含 tool_calls），否则下一轮上下文不完整。
    """
    response = llm.invoke(state["messages"])
    logger.info(f"llm_call: tool_calls={len(response.tool_calls) if response.tool_calls else 0}")
    return {"messages": [response]}


def should_continue(state: dict) -> str:
    """路由函数：看 AIMessage 有没有 tool_calls，并做轮数硬止损。

    这是 ReAct 的"继续与否"判定点 —— 由模型的 tool_calls 决定，
    但受 MAX_TOOL_ROUNDS 约束，避免模型陷入"信息不全 → 反复重试"的死循环。
    """
    messages = state["messages"]
    last = messages[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        tool_rounds = sum(
            1 for m in messages if isinstance(m, AIMessage) and m.tool_calls
        )
        if tool_rounds >= MAX_TOOL_ROUNDS:
            logger.warning(f"达到最大工具轮数 {MAX_TOOL_ROUNDS}，强制进入 report")
            return "report"
        return "tool_node"
    return "report"


def make_tool_node(tools: list) -> ToolNode:
    """构造 ToolNode（执行工具调用）。"""
    return ToolNode(tools)


def _strip_preamble(text: str) -> str:
    """去掉正文前的模型独白。

    模型偶发会把思考过程写进 content（如 "All three data sources returned. The news
    results are largely off-topic..."），这段英文独白会直接污染简报开头。
    启发式：报告正文一定以 Markdown 标题（`#`）开头，从第一个标题起截取。
    """
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("#"):
            return "\n".join(lines[i:]).strip()
    return text.strip()


def make_report_node(llm_plain) -> Callable[[dict], dict]:
    """构造报告节点。

    正常情况：模型最后一轮已输出正文 → 直接采用。
    兜底情况：模型只发了 tool_calls 没写正文（被硬止损拦下）→ 用不带 tools 的
    LLM 再调一次，强制它基于已有信息收尾，保证一定产出简报。
    """
    def report(state: dict) -> dict:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.content:
            text = _strip_preamble(last.content)
            logger.info(f"report: 采用模型输出 {len(text)} chars")
            return {"final_report": text}

        logger.warning("report: 模型未输出正文，触发强制收尾")
        msgs = list(state["messages"]) + [
            HumanMessage(content="请立即停止调用工具，基于以上全部信息直接输出 4 段简报。")
        ]
        resp = llm_plain.invoke(msgs)
        text = _strip_preamble(resp.content or "")
        logger.info(f"report: 强制收尾 {len(text)} chars")
        return {"final_report": text, "messages": [resp]}

    return report
