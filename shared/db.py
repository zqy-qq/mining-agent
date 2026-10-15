"""SQLite 数据层：储量表 + 价格表。

两张表都是单文件数据库（sqlite3 标准库），Python 直接读写。
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

from shared.config import SQLITE_PATH


def init_db() -> None:
    """初始化 SQLite 表结构（幂等）。"""
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(SQLITE_PATH)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS mineral_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mine_key TEXT NOT NULL,
                report_title TEXT,
                category TEXT,            -- Measured/Indicated/Inferred/Reserve
                tonnes TEXT,
                grade TEXT,
                source_page INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(mine_key, category, report_title)
            );

            CREATE TABLE IF NOT EXISTS price_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commodity TEXT NOT NULL,
                date TEXT NOT NULL,
                close REAL,
                UNIQUE(commodity, date)
            );

            CREATE INDEX IF NOT EXISTS idx_price_commodity_date
                ON price_daily(commodity, date);
        """)


def upsert_mineral(mine_key: str, report_title: str, items: list[dict]) -> int:
    """upsert 储量数据。items: [{"category","tonnes","grade","source_page"}]"""
    inserted = 0
    with sqlite3.connect(str(SQLITE_PATH)) as conn:
        for it in items:
            cur = conn.execute(
                """INSERT OR IGNORE INTO mineral_reports
                   (mine_key, report_title, category, tonnes, grade, source_page)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (mine_key, report_title,
                 it.get("category"), it.get("tonnes"), it.get("grade"),
                 it.get("source_page")),
            )
            if cur.rowcount > 0:
                inserted += 1
        conn.commit()
    return inserted


def upsert_prices(commodity: str, rows: list[dict]) -> int:
    """upsert 价格序列。rows: [{"date","close"}]"""
    inserted = 0
    with sqlite3.connect(str(SQLITE_PATH)) as conn:
        for r in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO price_daily (commodity, date, close) VALUES (?, ?, ?)",
                (commodity, r["date"], r["close"]),
            )
            if cur.rowcount > 0:
                inserted += 1
        conn.commit()
    return inserted


def get_mineral(mine_key: str) -> list[dict]:
    """查询某矿区所有储量记录。"""
    with sqlite3.connect(str(SQLITE_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM mineral_reports WHERE mine_key = ? ORDER BY category",
            (mine_key,),
        ).fetchall()]


def get_price_series(commodity: str, days: int) -> list[dict]:
    """查询某品种近 N 天价格。"""
    with sqlite3.connect(str(SQLITE_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            """SELECT date, close FROM price_daily
               WHERE commodity = ?
               ORDER BY date DESC LIMIT ?""",
            (commodity, days),
        ).fetchall()]


if __name__ == "__main__":
    init_db()
    print(f"[OK] SQLite 初始化完成 → {SQLITE_PATH}")
