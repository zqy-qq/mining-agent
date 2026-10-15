# 矿权日报 Agent

> 基于 MCP 协议的矿权日报生成系统：3 个 MCP server + 1 个 LangGraph 编排的 Agent client + Streamlit 前端，由模型按需并行调用 5 个工具，生成 4 段式日报。

## 5 分钟跑起来

### 1. 克隆 + 安装依赖

```bash
git clone <repo-url>
cd mining-rights-daily
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY（去 https://platform.deepseek.com 申请，5 分钟搞定）
```

### 3. 启动

**前端**：

```bash
streamlit run frontend/app.py
```

打开 `http://localhost:8501`，选矿区 → 点"生成日报"。

**或 CLI**（不开前端，结果存档到 `output/`）：

```bash
python -m agent.cli --mine pilbara          # 皮尔巴拉（锂 · JORC）
python -m agent.cli --mine thacker-pass     # 萨克帕斯（锂 · NI 43-101）
python -m agent.cli --mine haib             # 海博（铜 · NI 43-101）
python -m agent.cli "给我萨克帕斯矿区的今日日报"
```

## 项目结构

```
mining-rights-daily/
├── README.md                # 本文件
├── RUN.md                   # 部署与排障（含 docker-compose）
├── requirements.txt         # Python 依赖（锁版本）
├── mcp-config.json          # MCP 客户端配置（兼容 Claude Desktop / Cursor）
├── Dockerfile
├── docker-compose.yml
├── shared/                  # 共享配置、日志、SQLite
├── agent/                   # Agent 编排层
│   ├── graph.py             # StateGraph 主路径
│   ├── nodes.py             # 节点函数 + 路由 + 硬止损
│   ├── llm.py               # DeepSeek 接入 + system prompt
│   ├── mcp_client.py        # MCP 客户端（stdio 起 3 个 server）
│   └── cli.py               # 命令行入口
├── frontend/app.py          # Streamlit 单页
├── servers/                 # 3 个 MCP server
│   ├── mining_news/         # 新闻聚合（RSS 多源降级 + 正文抓取）
│   ├── mineral_pdf/         # 资源量（预抽索引 + 可选真抽）
│   └── lme_price/           # 价格行情（内置快照）
├── scripts/check_reports.py # 查看本地报告 PDF 状态
├── data/
│   ├── report_index.json    # 报告索引 + 预抽资源量数据
│   ├── entity_map.json      # 实体归一表（矿区别名 → 标准 key）
│   └── reports/             # 报告 PDF（不入库，可选放置）
└── output/                  # 生成的日报存档
```

## 三个 MCP Server

| Server | 工具 | 数据源 |
|---|---|---|
| `mining-news` | `search(query, days)` / `fetch_article(url)` | 公开 RSS，四源逐级降级 |
| `mineral-pdf` | `extract_resources(pdf_url)` | `report_index.json` 预抽数据 |
| `lme-price` | `get_price(commodity, date)` / `get_trend(commodity, days)` | 内置 30 天行情快照 |

传输方式统一 `stdio` —— 这样 `mcp-config.json` 能被 Claude Desktop / Cursor 直接加载。

## Agent 编排

**LangGraph `StateGraph`**（自写节点、条件边与回边）：

```
START → normalize → llm_call ⇄ tool_node → report → END
                         └─ 条件边 should_continue ─┘
```

- **条件边 `should_continue`**：读模型返回里的 `tool_calls` 字段，决定"继续调工具"还是"出报告"
- **回边 `tool_node → llm_call`**：ReAct 循环的物理实现（`add_edge` 一条普通边即可成环）
- **硬止损**：最多 3 轮工具调用（`MAX_TOOL_ROUNDS`），`recursion_limit=12`
- **兜底收尾**：若被止损时模型还没写正文，`report` 节点用不带 tools 的 LLM 强制出稿

三条数据线完全解耦：任一 server 失败，其余照常，对应段落如实写"该数据源暂不可用"。

## 数据源策略

| 数据线 | 策略 | 断网表现 |
|---|---|---|
| 新闻 | RSS 四源逐级降级（Google News 中/英 → Bing → mining.com） | 返回空列表，报告如实标注 |
| 储量 | `report_index.json` 预抽数据（人工核对） | 无影响 |
| 价格 | 内置 30 天行情快照 | 无影响 |

**断网也能完整跑出 4 段日报** —— 面试官 clone 后无需任何额外准备。

> **关于 PDF 真抽**：把报告 PDF 放进 `data/reports/` 并设 `ENABLE_PDF_EXTRACT=1` 可启用
> `pdfplumber` 真抽。默认关闭 —— 真实 NI 43-101 / JORC 报告表格版式差异极大（单位在表头、
> 分类重复出现、扫件跨页），脚本抽取准确率不可控，**给 Agent 喂错误数据比缺数据更危险**。
> 查看本地报告状态：`python -m scripts.check_reports`

## Docker 启动

```bash
docker-compose up        # 前端 http://localhost:8501
```

## 验收

| 维度 | 要求 |
|---|---|
| 启动时长 | ≤ 5 分钟 |
| 简报结构 | 4 段（新闻摘要 / 储量数据 / 价格走势 / 风险提示） |
| 引用格式 | `[1][2]` + 文末链接 |
| 输出长度 | 800~1500 字 |
| 失败降级 | 单点失败不阻断，如实标注缺失 |
