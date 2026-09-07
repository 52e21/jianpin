"""执行历史记录：SQLite 存储。

每次 Agent 任务执行完成后，将任务内容、输出、统计信息写入
backend/data/history.db，供前端历史记录页查询。
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "history.db"


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT NOT NULL,
                result TEXT NOT NULL,
                llm_calls INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cache_hit INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                job_url TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        # 兼容旧库：若已存在表但缺 job_url 列，则 ALTER TABLE 追加（不清数据）
        cols = [row[1] for row in conn.execute("PRAGMA table_info(execution_history)").fetchall()]
        if "job_url" not in cols:
            conn.execute("ALTER TABLE execution_history ADD COLUMN job_url TEXT DEFAULT ''")


def save_history(task, result, llm_calls, total_tokens, cache_hit, duration_ms, job_url=""):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO execution_history
               (task, result, llm_calls, total_tokens, cache_hit, duration_ms, job_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task,
                result,
                llm_calls,
                total_tokens,
                1 if cache_hit else 0,
                duration_ms,
                job_url or "",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def fetch_history(limit=50, offset=0):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM execution_history ORDER BY id DESC LIMIT ? OFFSET ?",
            (min(max(int(limit), 1), 200), max(int(offset), 0)),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM execution_history").fetchone()[0]
    return [dict(row) for row in rows], int(total)


def delete_history(history_id: int) -> bool:
    """删除单条历史记录；不存在返回 False。"""
    with get_conn() as conn:
        cursor = conn.execute("DELETE FROM execution_history WHERE id = ?", (history_id,))
        return cursor.rowcount > 0


def clear_history() -> int:
    """清空全部历史记录；返回删除行数。"""
    with get_conn() as conn:
        cursor = conn.execute("DELETE FROM execution_history")
        return cursor.rowcount
