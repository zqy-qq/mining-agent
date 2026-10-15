# 矿权日报 Agent

> 基于 MCP 协议的矿权日报生成系统：3 个 MCP server + 1 个 LangGraph 编排的 Agent client + Streamlit 前端，由模型按需并行调用 5 个工具，生成 4 段式日报。

## 5 分钟跑起来

### 1. 克隆 + 安装依赖

> 环境要求：Python ≥ 3.11（本项目在 3.13.14 上验证通过）

```bash
git clone https://github.com/zqy-qq/mining-agent.git
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
│   ├── mining_news/         # 新闻聚合（mining.com 检索 RSS，时效优先降级）
│   ├── mineral_pdf/         # 资源量（预抽索引 + 可选真抽）
│   └── lme_price/           # 价格行情（LME/广期所真实源 + 降级）
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
| `mining-news` | `search(query, days)` / `fetch_article(url)` | mining.com 检索 RSS（三源），**时效优先**降级 |
| `mineral-pdf` | `extract_resources(pdf_url)` | `report_index.json` 预抽数据 |
| `lme-price` | `get_price(commodity, date)` / `get_trend(commodity, days)` | 新浪财经公开接口：LME 外盘（美元）+ 广期所（人民币），失败降级内置基准价 |

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
| 新闻 | mining.com 检索 RSS 三源（关键词搜索 → 最新 feed → Nasdaq 兜底）；检索词按「矿区名+矿种」→「矿区名」→「矿种」放宽，**以时效优先**：只返回窗口内命中，窗口内零命中时返回 `in_window=false` 并声明「非本期新闻」 | 外呼失败逐源降级；全失败返回 `count=0`，报告如实标注 |
| 储量 | `report_index.json` 预抽数据（人工核对） | 无影响 |
| 价格 | **真实行情优先**：新浪财经公开接口（免费无 key）—— 铜/镍/铝/锌/锡/铅走 LME 外盘（美元/吨），锂走广期所碳酸锂（人民币元/吨）；锂辉石、钴无对应期货合约 | 自动降级内置基准价，报告标注「模拟，非实时行情」 |

### 价格数据源（真实行情）

| 品种 | 源 | 单位 | 口径 |
|---|---|---|---|
| 铜 `copper` | LME 伦铜（新浪外盘 `hf_CAD`） | USD/t | LME 官方报价，真实 |
| 镍 `nickel` | LME 伦镍（`hf_NID`） | USD/t | 真实 |
| 铝 / 锌 / 锡 / 铅 | LME 对应合约（`hf_AHD`/`ZSD`/`SND`/`PBD`） | USD/t | 真实 |
| 锂 `lithium` | 广期所碳酸锂（新浪内盘 `nf_LC0`） | CNY/t | 国内期货主力连续，真实 |
| 锂辉石 `spodumene` / 钴 `cobalt` | 内置基准价 | USD/t | 无期货合约，**模拟** |

- 快照与 30 日历史日线均取自同一公开接口，返回体带 `source`（`sina-lme` / `sina-gfex` / `fallback-mock`）与 `source_name`、`unit` 字段，报告直接引用，**不自行换算币种**。
- 拿到陈旧数据（>15 天）时按失败处理并降级 —— 新浪内盘代码漏 `nf_` 前缀会 HTTP 200 返回约两年前的报价，此校验即为此设。

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
