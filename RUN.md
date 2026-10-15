# RUN.md — 5 分钟跑起来

## 方式一：本地 Python（推荐）

### 前置要求

- Python 3.11+（推荐 3.13）
- pip 23+

### 步骤

```bash
# 1. 克隆仓库
git clone <repo-url>
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
docker-compose build

# 2. 启动
docker-compose up
# 前端访问 http://localhost:8501
```

### docker-compose.yml 简化版

```yaml
version: "3.8"
services:
  app:
    build: .
    ports:
      - "8501:8501"
    env_file:
      - .env
    volumes:
      - ./data:/app/data
      - ./output:/app/output
```

## 验证清单

| 步骤 | 预期 |
|---|---|
| `python -c "from shared.config import require_api_key; require_api_key()"` | 配 key 后无报错 |
| `python -m scripts.check_reports` | 打印 3 个矿区的报告状态与来源页 |
| `python -m servers.lme_price.server` | 启动 stdio server（Ctrl+C 退出） |
| `python -m servers.mineral_pdf.server` | 同上 |
| `python -m servers.mining_news.server` | 同上 |
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
| 新闻搜不到 | 检索词会自动放宽（矿区名+矿种 → 矿区名 → 矿种泛词，时效优先）。三源全失败才返回 `count=0`；若报告出现「本期未检索到有效新闻」，多为该检索窗口内确实没有新报道，`in_window=false` 即此意，属正常降级非故障 |
| Streamlit 卡死 | 第一次跑 LangGraph 较慢（5-10 秒），等一会儿 |

