"""检查 data/reports/ 下的报告 PDF 状态。

mineral-pdf server 采用双保险：
- data/reports/ 下有对应 PDF → pdfplumber 真抽表格
- 没有 / 抽不到 → 回退 report_index.json 的 fallback 预抽数据

所以本脚本不影响运行，只是帮你确认"真抽分支"当前是否可用。

用法：
    python -m scripts.check_reports
"""
from __future__ import annotations
import sys
from pathlib import Path

from shared.config import REPORTS_DIR, ROOT, load_report_index


def main() -> int:
    index = load_report_index()
    keys = [k for k in index if not k.startswith("_")]

    print(f"报告目录：{REPORTS_DIR}")
    print("（目录不存在或为空不影响运行，会自动走 fallback 预抽数据）")
    print()

    n_ready = n_missing = 0
    for key in keys:
        mine = index[key]
        print(f"● {mine['name_cn']}  [{key}]  标准={mine['disclosure_standard']}")
        for rep in mine.get("reports", []):
            dest = Path(rep["local_path"])
            if not dest.is_absolute():
                dest = ROOT / dest
            if dest.exists() and dest.stat().st_size > 0:
                n_ready += 1
                size = dest.stat().st_size / 1024 / 1024
                print(f"    PDF    : {dest.name}  ({size:.1f} MB)  → 真抽")
            else:
                n_missing += 1
                print(f"    PDF    : {dest.name}  (缺失)  → fallback")
            print(f"    来源页 : {rep.get('source_page') or rep.get('url') or '-'}")
            print(f"    提示页 : 第 {rep.get('hint_resource_table_page', '-')} 页")
        print()

    print(f"汇总：本地 PDF {n_ready} 份 / 缺失 {n_missing} 份")
    print("缺失时无需处理 —— agent 会自动使用 report_index.json 的 fallback 预抽数据。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
