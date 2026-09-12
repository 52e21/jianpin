# -*- coding: utf-8 -*-
"""
演示数据清理（**部署前请跑一次**）

背景：`frontend/src/routes/match.tsx` 的「填入示例」会带入示例手机号/邮箱
（`13800138000` / `zhangsan@email.com`，都是虚构值），演示时产生的历史行会带着它们进库。
本脚本把命中这些标记的历史行**备份后删除**，避免部署后把演示数据当真实数据留下。

用法：
  python eval/clear_demo_data.py            # 只报告，不删（dry-run）
  python eval/clear_demo_data.py --yes      # 备份到 data/demo_rows_backup_*.json 后删除

只删命中演示标记的行；不碰其它历史数据。
"""
import argparse
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DB = BACKEND / "data" / "history.db"
DEMO_MARKERS = ("13800138000", "zhangsan@email.com")
PHONE_RE = re.compile(r"(?<![\d.])1[3-9]\d{9}(?![\d])")


def find_demo_rows(conn) -> list:
    out = []
    for r in conn.execute("SELECT * FROM execution_history"):
        d = dict(r)
        blob = " ".join(str(v) for v in d.values() if v is not None)
        marks = [m for m in DEMO_MARKERS if m in blob]
        phones = sorted(set(PHONE_RE.findall(blob)))
        if marks or phones:
            out.append({"row": d, "markers": marks, "phones": phones})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="确认删除（默认为 dry-run）")
    a = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    hits = find_demo_rows(conn)
    total = conn.execute("SELECT COUNT(*) FROM execution_history").fetchone()[0]
    print("  库: %s" % DB)
    print("  命中演示标记的行: %d / %d" % (len(hits), total))
    for h in hits:
        d = h["row"]
        print("    id=%-4s task_id=%-18s created=%-19s markers=%s phones=%s" % (
            d.get("id"), d.get("task_id") or "-", d.get("created_at"),
            h["markers"] or "-", h["phones"] or "-"))

    if not hits:
        print("  无需清理 ✔")
        return 0
    if not a.yes:
        print("\n  当前为 dry-run；确认删除请加 --yes")
        return 0

    bak = BACKEND / "data" / ("demo_rows_backup_%s.json" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    with io.open(bak, "w", encoding="utf-8") as f:
        json.dump([h["row"] for h in hits], f, ensure_ascii=False, indent=2)
    ids = [h["row"]["id"] for h in hits]
    tids = [h["row"]["task_id"] for h in hits if h["row"].get("task_id")]
    n_h = 0
    for i in ids:
        n_h += conn.execute("DELETE FROM execution_history WHERE id = ?", (i,)).rowcount
    n_t = 0
    for t in tids:
        n_t += conn.execute("DELETE FROM trace_events WHERE task_id = ?", (t,)).rowcount
    conn.commit()
    left = conn.execute("SELECT COUNT(*) FROM execution_history").fetchone()[0]
    print("\n  备份: %s" % bak)
    print("  删除: execution_history=%d（ids=%s）trace_events=%d" % (n_h, ids, n_t))
    print("  剩余历史行: %d" % left)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
