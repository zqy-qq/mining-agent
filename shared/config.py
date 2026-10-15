"""共享配置：环境变量、项目根路径、实体归一表加载。"""
from __future__ import annotations
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent

# 加载 .env（如果存在）
load_dotenv(ROOT / ".env")

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.3"))
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "2000"))

# 日志
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 数据路径
DATA_DIR = ROOT / "data"
REPORT_INDEX_PATH = DATA_DIR / "report_index.json"
ENTITY_MAP_PATH = DATA_DIR / "entity_map.json"
REPORTS_DIR = DATA_DIR / "reports"
SQLITE_PATH = DATA_DIR / "mining.db"

# 输出路径
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_report_index() -> dict:
    """加载报告索引（含 fallback 预抽数据）。"""
    if not REPORT_INDEX_PATH.exists():
        return {}
    with open(REPORT_INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_entity_map() -> dict:
    """加载实体归一表：矿别名 → 标准矿区 key。"""
    if not ENTITY_MAP_PATH.exists():
        return {}
    with open(ENTITY_MAP_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def require_api_key() -> str:
    """启动时校验 API Key 是否存在。"""
    if not DEEPSEEK_API_KEY:
        raise SystemExit(
            "❌ DEEPSEEK_API_KEY 未配置。\n"
            "1. 复制 .env.example 为 .env：cp .env.example .env\n"
            "2. 去 https://platform.deepseek.com 申请 API Key（5 分钟）\n"
            "3. 把 key 填到 .env 的 DEEPSEEK_API_KEY= 后面"
        )
    return DEEPSEEK_API_KEY
