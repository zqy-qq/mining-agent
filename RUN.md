# RUN.md — 5 分钟跑起来

## 方式一：本地 Python（推荐）

### 前置要求

- Python 3.11+（推荐 3.13）
- pip 23+

### 步骤

```bash
# 1. 克隆仓库
git clone https://github.com/zqy-qq/mining-agent.git
cd mining-rights-daily

# 2. 安装依赖（约 1 分钟）
pip install -r requirements.txt

# 3. 配置 API Key（约 1 分钟）
cp .env.example .env
# 编辑 .env，把 DEEPSEEK_API_KEY= 后填上你的 key
# 申请地址：https://platform.deepseek.com

# 4. 启动 Streamlit 前端
streamlit run frontend/app.py
# 打开浏览器 http://localhost:8501
```

### CLI 方式（不开前端）

```bash
# 单次跑图 + 存档到 output/
python -m agent.cli "给我萨克帕斯锂矿的今日日报"

# 指定矿区
python -m agent.cli --mine thacker-pass --days 7
```

## 方式二：Docker

### 前置要求

- Docker Desktop 4.0+

### 步骤

```bash
# 1. 构建镜像
docker compose build

# 2. 启动
docker compose up -d
# 前端访问 http://localhost:8501
```

**国内网络加速（可选）**：在 `.env` 里加一行 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`，
compose 会作为 build arg 传给 Dockerfile 换 pip 源；Docker Hub 拉基础镜像慢则给 Docker Desktop
配镜像加速器（设置 → Docker Engine → `registry-mirrors`）。

> 本机实测（含加速）：构建 4 分 23 秒，容器内跑完一份完整日报 27.8 秒。

### docker-compose.yml 说明

```yaml
services:
  app:
    build: .
    ports:
      - "8501:8501"
    environment:
      DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}   # 自动读同目录 .env，缺失时回退空值
      DEEPSEEK_MODEL: ${DEEPSEEK_MODEL:-deepseek-chat}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    volumes:
      - ./data:/app/data
      - ./output:/app/output
```

- 用 `environment` + 插值而非 `env_file`：`.env` 不存在时由应用在运行时报"key 未配置"，
  而不是 Compose 直接启动失败（面试官 clone 后忘记 `cp .env.example .env` 也不会卡住）
- 不写 `version:` —— 新版 Compose 已废弃该字段
- `.dockerignore` 排除 `.env`、报告 PDF、`output/`，密钥不进镜像层

## 接入 Claude Desktop / Cursor（MCP 客户端验证）

`mcp-config.json` 里的路径是占位符，**先替换成仓库绝对路径**：

```json
"args": ["C:/Users/you/mining-rights-daily/scripts/mcp_launch.py", "mining-news"]
```

| 客户端 | 配置文件位置 |
|---|---|
| Claude Desktop | `claude_desktop_config.json`（设置 → Developer → Edit Config） |
| Cursor | `~/.cursor/mcp.json`，或仓库内 `.cursor/mcp.json` |

把 `mcpServers` 整段合并进去，重启客户端，工具列表应出现 5 个工具。

> 为什么需要 `scripts/mcp_launch.py`：Claude Desktop 不支持 `${workspaceFolder}`，
> 也不会把子进程 cwd 设为仓库根，直接写 `python -m servers.xxx.server` 会报
> `ModuleNotFoundError: No module named 'servers'`。启动器用自身路径反推仓库根并注入
> `sys.path`，从任意 cwd 都能拉起。已实测三个 server 均正常启动。
>
> `python` 不在 PATH 时换成解释器绝对路径（macOS / Linux 常为 `python3`）。

## 验证清单

| 步骤 | 预期 |
|---|---|
| `python -c "from shared.config import require_api_key; require_api_key()"` | 配 key 后无报错 |
| `python -m scripts.check_reports` | 打印 3 个矿区的报告状态与来源页 |
| `python scripts/mcp_launch.py mining-news` | 启动 stdio server（Ctrl+C 退出）；换成 `mineral-pdf` / `lme-price` 验证另外两个。任意 cwd 均可，不依赖 PYTHONPATH |
| `python -m servers.lme_price.server` | 同上（需在仓库根目录执行） |
| `python -m agent.cli --mine pilbara` | 输出 4 段简报，存档到 `output/` |
| `streamlit run frontend/app.py` | 浏览器访问 8501 |

## 可选：启用 PDF 真抽

默认使用 `data/report_index.json` 中人工核对的预抽数据，**不需要任何 PDF 也能跑**。

若想演示 `pdfplumber` 真抽，把报告 PDF 放进 `data/reports/`（文件名需与 `report_index.json`
里的 `local_path` 一致），然后设环境变量：

```bash
# Windows
set ENABLE_PDF_EXTRACT=1

# macOS / Linux
export ENABLE_PDF_EXTRACT=1
```

抽到结果会返回 `source: "pdf"`，抽不到自动回退 `source: "fallback"`。

> 为什么默认关闭：真实 NI 43-101 / JORC 报告表格版式差异极大（单位写在表头、同一分类重复
> 出现、扫描件跨页），脚本抽取准确率不可控且会**静默出错**。给 Agent 喂错误储量数据，
> 比不给数据危险得多。

## 故障排查

| 问题 | 解决 |
|---|---|
| `DEEPSEEK_API_KEY 未配置` | 检查 .env 是否存在并填值 |
| `ModuleNotFoundError: shared` | 在项目根目录运行命令，或设 `PYTHONPATH=.` |
| `ModuleNotFoundError: itsdangerous` | Streamlit 依赖缺失：`pip install itsdangerous` |
| `mcp server 启动失败` | 检查 Python 版本 ≥ 3.11；`pip show fastmcp` 看是否安装 |
| 中文查询乱码 / 搜不到 | 确认 `agent/mcp_client.py` 给子进程设了 `PYTHONIOENCODING=utf-8` |
| `GraphRecursionError` | 模型陷入重试循环。已设 3 轮硬止损；若仍触发说明 system prompt 被改动 |
| `pdfplumber 装不上` | Windows 下需 Visual C++ 14+；或用 conda `conda install pdfplumber` |
| `docker compose build` 卡在拉基础镜像 | Docker Hub 网络问题，给 Docker Desktop 配 `registry-mirrors` 加速器 |
| `docker compose build` 卡在 pip | 国内网络，在 `.env` 加 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` |
| `docker compose up` 报端口被占用 | 本机已有 8501 进程（如另一份 Streamlit），先停掉或改 `ports` 映射 |
| 新闻搜不到 | 检索词会自动放宽（矿区名+矿种 → 矿区名 → 矿种泛词，时效优先）。三源全失败才返回 `count=0`；若报告出现「本期未检索到有效新闻」，多为该检索窗口内确实没有新报道，`in_window=false` 即此意，属正常降级非故障 |
| Streamlit 卡死 | 第一次跑 LangGraph 较慢（5-10 秒），等一会儿 |

