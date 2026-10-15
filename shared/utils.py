"""共享工具：日志、JSON 序列化辅助。"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime

from shared.config import LOG_LEVEL


def get_logger(name: str) -> logging.Logger:
    """统一日志格式。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = "[%(asctime)s] %(name)s %(levelname)s: %(message)s"
        handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    return logger


def safe_json(obj) -> str:
    """安全的 JSON 序列化（处理 datetime 等不可序列化对象）。"""
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, "model_dump"):
            return o.model_dump()
        if hasattr(o, "__dict__"):
            return o.__dict__
        return str(o)
    return json.dumps(obj, ensure_ascii=False, default=default, indent=2)


def today_str() -> str:
    """返回 YYYY-MM-DD 格式的今天日期。"""
    return datetime.now().strftime("%Y-%m-%d")
