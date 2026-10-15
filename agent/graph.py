"""LangGraph StateGraph 主路径。

5 节点 + 1 条件边 + 1 回边（约 40 行）：
  START → normalize → llm_call ⇄ tool_node → report → END

回边（add_edge("tool_node", "llm_call")）就是 ReAct 循环的物理实现。

⚠️ State 必须显式声明每个通道：LangGraph 只保留 schema 里声明过的 key，
   用 MessagesState 的话 matched_mine / final_report 会被静默丢弃。
"""
from __future__ import annotations
from typing import Annotated, Any, TypedDict

from langgraph.graph import StateGraph, START, END, add_messages

from agent.nodes import (
    normalize, llm_call, should_continue, make_tool_node, make_report_node,
)
from agent.llm import get_llm, SYSTEM_PROMPT
from shared.utils import get_logger

logger = get_logger("agent.graph")


class AgentState(TypedDict):
    """图状态。

    - messages: 累加语义（add_messages 归约器），每轮追加
    - matched_mine / final_report: 覆盖语义（最后写入者胜）
    """
    messages: Annotated[list, add_messages]
    matched_mine: str
    final_report: str


def build_graph(tools: list):
    """构造编译后的 LangGraph app。"""
    llm = get_llm(tools=tools)          # 带工具：用于 llm_call
    llm_plain = get_llm(tools=None)     # 不带工具：用于 report 兜底收尾
    tool_node = make_tool_node(tools)

    g = StateGraph(AgentState)
    g.add_node("normalize", normalize)
    g.add_node("llm_call", lambda s: llm_call(s, llm))
    g.add_node("tool_node", tool_node)
    g.add_node("report", make_report_node(llm_plain))

    g.add_edge(START, "normalize")
    g.add_edge("normalize", "llm_call")
    g.add_conditional_edges(
        "llm_call",
        should_continue,
        {"tool_node": "tool_node", "report": "report"},
    )
    g.add_edge("tool_node", "llm_call")  # ← 回边 = ReAct 循环
    g.add_edge("report", END)

    return g.compile()


# 最大轮数（防死循环）：在 ainvoke/astream 时通过 config 传入
# 每轮 = 1 次 llm_call + 1 次 tool_node，正常 1~3 轮工具调用，留余量给 12
GRAPH_CONFIG = {"recursion_limit": 12}


def _init_state(query: str) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage
    return {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=query),
        ],
        "matched_mine": "",
        "final_report": "",
    }


async def run(query: str, tools: list) -> str:
    """跑图：返回最终 4 段简报。"""
    app = build_graph(tools)
    final = await app.ainvoke(_init_state(query), config=GRAPH_CONFIG)
    return final.get("final_report", "")


async def stream(query: str, tools: list):
    """流式跑图：逐节点 yield 状态，前端可实时显示轨迹。"""
    app = build_graph(tools)
    async for event in app.astream(
        _init_state(query), config=GRAPH_CONFIG, stream_mode="updates"
    ):
        yield event
