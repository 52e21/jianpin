"""执行历史记录：SQLite 存储。

每次 Agent 任务执行完成后，将任务内容、输出、统计信息写入
backend/data/history.db，供前端历史记录页查询。
"""

import json
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
        # 兼容旧库：缺列则 ALTER TABLE 追加（不清数据）
        cols = [row[1] for row in conn.execute("PRAGMA table_info(execution_history)").fetchall()]
        if "job_url" not in cols:
            conn.execute("ALTER TABLE execution_history ADD COLUMN job_url TEXT DEFAULT ''")

        # ---- 第 7 步：任务标识 + 反馈列 ----
        # task_id：执行书要求反馈接口按 task_id 定位任务，而原表只有自增 id，
        #          故新增该列（与 trace_events.task_id 对应）。
        if "task_id" not in cols:
            conn.execute("ALTER TABLE execution_history ADD COLUMN task_id TEXT DEFAULT ''")
        if "feedback" not in cols:
            conn.execute("ALTER TABLE execution_history ADD COLUMN feedback TEXT")
        if "feedback_at" not in cols:
            conn.execute("ALTER TABLE execution_history ADD COLUMN feedback_at TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_task ON execution_history(task_id)")

        # ---- 第 4 步：节点级 Trace 表 ----
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trace_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT,
                task_id TEXT,
                node_name TEXT,
                input_hash TEXT,
                output_json TEXT,
                tokens INTEGER,
                latency_ms INTEGER,
                degraded INTEGER,
                degrade_reason TEXT,
                raw_response TEXT,
                finish_reason TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_id ON trace_events(trace_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_task ON trace_events(task_id)")

        # ---- A1（Agent 子模块）：追问会话状态，按 session_id 挂载 ----
        # 执行书 A1 要求「后端用 session_id 挂载追问状态，能查到」；A2–A5 复用同一张表：
        # status 记录会话阶段，round 记录追问轮数（上限 2），pending_questions 存待回答的追问。
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ask_sessions (
                session_id TEXT PRIMARY KEY,
                tenant_id TEXT DEFAULT 'default',
                role TEXT DEFAULT 'hr',
                jd TEXT DEFAULT '',
                resume TEXT DEFAULT '',
                job_url TEXT DEFAULT '',
                round INTEGER DEFAULT 0,
                status TEXT DEFAULT 'idle',
                pending_questions TEXT DEFAULT '',
                merged_jd TEXT DEFAULT '',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ask_sessions_updated ON ask_sessions(updated_at)")


def save_history(task, result, llm_calls, total_tokens, cache_hit, duration_ms, job_url="", task_id=""):
    """写入一条执行历史，返回自增 id（第 7 步起同时落 task_id）。"""
    with get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO execution_history
               (task, result, llm_calls, total_tokens, cache_hit, duration_ms, job_url, task_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task,
                result,
                llm_calls,
                total_tokens,
                1 if cache_hit else 0,
                duration_ms,
                job_url or "",
                task_id or "",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return cursor.lastrowid


# ---------------------------------------------------------------------------
# 第 7 步：反馈写入 / 读取
# ---------------------------------------------------------------------------
def set_feedback(task_id: str, feedback) -> dict:
    """按 task_id 写入反馈（feedback 建议传 JSON 字符串）。

    返回 {"updated": 命中行数, "feedback_at": 时间戳}；未命中时 updated=0。
    """
    ts = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        cursor = conn.execute(
            """UPDATE execution_history
                  SET feedback = ?, feedback_at = ?
                WHERE id = (SELECT id FROM execution_history
                             WHERE task_id = ? AND task_id <> ''
                             ORDER BY id DESC LIMIT 1)""",
            (feedback, ts, task_id),
        )
        return {"updated": cursor.rowcount, "feedback_at": ts}


def fetch_history_by_task(task_id: str):
    """按 task_id 取该次任务的历史行（含已写入的反馈）。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM execution_history WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    return dict(row) if row else None


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


# ---------------------------------------------------------------------------
# 第 4 步：节点级 Trace（trace_events）
# ---------------------------------------------------------------------------
def insert_trace(trace_id, task_id, node_name, input_hash="", output_json="",
                 tokens=0, latency_ms=0, degraded=False, degrade_reason="",
                 raw_response="", finish_reason=""):
    """写入一条节点级 Trace。"""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO trace_events
               (trace_id, task_id, node_name, input_hash, output_json, tokens, latency_ms,
                degraded, degrade_reason, raw_response, finish_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace_id, task_id, node_name, input_hash, output_json,
                int(tokens or 0), int(latency_ms or 0), 1 if degraded else 0,
                degrade_reason or "", raw_response or "", finish_reason or "",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def fetch_traces(trace_id=None, task_id=None, limit=100):
    """按 trace_id / task_id 查 Trace（后续 Badcase 归因用）。"""
    sql = "SELECT * FROM trace_events"
    where, args = [], []
    if trace_id:
        where.append("trace_id = ?")
        args.append(trace_id)
    if task_id:
        where.append("task_id = ?")
        args.append(task_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC LIMIT ?"
    args.append(min(max(int(limit), 1), 1000))
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [dict(r) for r in rows]


def count_traces(trace_id=None) -> int:
    with get_conn() as conn:
        if trace_id:
            return int(conn.execute(
                "SELECT COUNT(*) FROM trace_events WHERE trace_id = ?", (trace_id,)).fetchone()[0])
        return int(conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0])


# ---------------------------------------------------------------------------
# A1（Agent 子模块）：追问会话状态
# ---------------------------------------------------------------------------
ASK_STATUSES = ("idle", "insufficient", "answered", "done")


def upsert_ask_session(session_id, tenant_id="default", role="hr", jd=None, resume=None,
                       job_url=None, status=None, round_no=None, pending_questions=None,
                       merged_jd=None) -> dict:
    """按 session_id 挂载/更新追问状态；**只更新显式传入的字段**（None = 不动）。

    这是 A1 的核心：同一个 session_id 的多次请求共享一份状态（追问轮数、待答问题、合并后的 JD）。
    """
    session_id = (session_id or "").strip()
    if not session_id:
        raise ValueError("session_id 不能为空")
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO ask_sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now))
        sets, args = ["updated_at = ?"], [now]
        for col, val in (("tenant_id", tenant_id), ("role", role), ("jd", jd), ("resume", resume),
                         ("job_url", job_url), ("status", status), ("merged_jd", merged_jd)):
            if val is not None:
                sets.append(col + " = ?")
                args.append(val)
        if round_no is not None:
            sets.append("round = ?")
            args.append(int(round_no))
        if pending_questions is not None:
            sets.append("pending_questions = ?")
            args.append(pending_questions if isinstance(pending_questions, str)
                        else json.dumps(pending_questions, ensure_ascii=False))
        args.append(session_id)
        conn.execute("UPDATE ask_sessions SET " + ", ".join(sets) + " WHERE session_id = ?", tuple(args))
        row = conn.execute("SELECT * FROM ask_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return dict(row) if row else {}


def fetch_ask_session(session_id):
    """按 session_id 查询追问状态（None 表示没有挂载过）。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ask_sessions WHERE session_id = ?",
                           ((session_id or "").strip(),)).fetchone()
    return dict(row) if row else None


def delete_ask_session(session_id) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM ask_sessions WHERE session_id = ?", ((session_id or "").strip(),))
        return cur.rowcount > 0
