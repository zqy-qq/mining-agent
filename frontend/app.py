"""Streamlit 单页前端。

布局（全部在主区，避免侧栏在窄窗口被自动折叠）：
- 顶部：标题 + 一行操作区（矿区选择 | 查询输入 | 生成按钮）
- 中部：流式生成的 4 段简报 + 工具调用轨迹
- 底部：下载 .md
"""
from __future__ import annotations
import asyncio
import streamlit as st

from agent.graph import build_graph, stream
from agent.mcp_client import get_tools
from agent.llm import SYSTEM_PROMPT
from shared.config import OUTPUT_DIR, load_report_index
from shared.utils import get_logger, today_str

logger = get_logger("frontend")
st.set_page_config(page_title="矿权日报 Agent", page_icon="⛏️", layout="wide")


@st.cache_resource
def load_mcp_tools():
    """缓存 MCP 工具列表（避免每次重连）。"""
    return asyncio.run(get_tools())


@st.cache_data
def load_index():
    """缓存矿区索引。"""
    return load_report_index()


def main():
    st.title("⛏️ 矿权日报 Agent")
    st.caption("基于 MCP + LangGraph StateGraph | 输入查询 → 3 server 并发取数 → 4 段日报")

    report_index = load_index()
    mine_keys = list(report_index.keys())
    mine_labels = {k: report_index[k]["name_cn"] for k in mine_keys}

    # 操作区：矿区选择 / 查询输入 / 生成按钮 —— 全部放主区
    c1, c2, c3 = st.columns([1.3, 2.7, 1], vertical_alignment="bottom")
    with c1:
        selected = st.selectbox(
            "矿区",
            options=mine_keys,
            format_func=lambda k: mine_labels[k],
            help="可选矿区；也可直接在下框输入别名（如 PLS / McDermitt / Koryx）",
        )
    with c2:
        query = st.text_input(
            "查询",
            key=f"query_{selected}",
            value=f"给我{mine_labels[selected]}矿区的今日日报",
            placeholder="如：给我萨克帕斯锂矿的今日日报",
        )
    with c3:
        run_btn = st.button("🚀 生成日报", type="primary", use_container_width=True)

    info = report_index[selected]
    st.caption(
        f"矿种 {info['commodity']} ｜ 披露标准 {info['disclosure_standard']} ｜ 运营方 {info['operator']}"
    )

    if not run_btn:
        st.info("填好查询后点「生成日报」。首次约 5~10 秒（起 3 个 MCP 子进程 + 调模型）。")
        return

    # 加载工具
    with st.spinner("加载 MCP 工具..."):
        tools = load_mcp_tools()

    st.success(f"已加载 {len(tools)} 个工具：{[t.name for t in tools]}")

    # 流式跑图
    placeholder = st.empty()
    trajectory = st.expander("🔧 工具调用轨迹", expanded=False)
    final_text = ""

    with trajectory:
        step_box = st.container()

    async def run_async():
        nonlocal final_text
        async for event in stream(query, tools):
            for node_name, node_state in event.items():
                with step_box:
                    st.markdown(f"**[{node_name}]**")
                    if "messages" in node_state:
                        for m in node_state["messages"]:
                            kind = type(m).__name__
                            preview = (m.content[:200] + "...") if m.content and len(m.content) > 200 else (m.content or "")
                            st.text(f"  {kind}: {preview}")
                    if node_name == "report" and "final_report" in node_state:
                        final_text = node_state["final_report"]
                        with placeholder.container():
                            st.markdown(final_text)

    asyncio.run(run_async())

    if final_text:
        st.markdown("---")
        st.markdown(final_text)

        # 下载按钮
        col_dl, col_save = st.columns([1, 3])
        with col_dl:
            st.download_button(
                "📥 下载 .md",
                data=final_text,
                file_name=f"{today_str()}_{selected}.md",
                mime="text/markdown",
            )
        with col_save:
            save_path = OUTPUT_DIR / f"{today_str()}_{selected}.md"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(final_text, encoding="utf-8")
            st.caption(f"已存档 → {save_path}")


if __name__ == "__main__":
    main()
