# -*- coding: utf-8 -*-
"""节点级 Trace 工具（第 5 步用）。

设计要点：
- trace_id 标识"一次完整分析"，task_id 标识"一个业务任务"（第 7 步反馈接口会用到）。
  目前一次 analyze 调用 = 一个 task，因此 task_id 与 trace_id 一一对应，但保留两个字段
  是为了将来支持"一个任务多轮重试/多次分析"。
- 写入失败绝不影响主链路：所有异常只记 warning。
- raw_response 截断到 2000 字符（执行书要求）；output_json 截断到 4000 字符防止长文本撑爆表。
- _ENABLED 开关：跑批时关掉，避免评测数据污染 Trace 表。
"""
import hashlib
import json
import logging
import uuid
from typing import Any

from . import database

logger = logging.getLogger("trace")

MAX_RAW_RESPONSE = 2000
MAX_OUTPUT_JSON = 4000

_ENABLED = True


def set_enabled(value: bool):
    global _ENABLED
    _ENABLED = bool(value)


def is_enabled() -> bool:
    return _ENABLED


def new_trace_id() -> str:
    return "tr_" + uuid.uuid4().hex[:16]


def new_task_id() -> str:
    return "tk_" + uuid.uuid4().hex[:12]


def hash_input(*parts: Any) -> str:
    """对节点输入做稳定哈希（不存原文，避免隐私与体积问题）。"""
    blob = "\u0001".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + f"...<truncated,original={len(text)}>"


def dump(obj: Any, limit: int = MAX_OUTPUT_JSON) -> str:
    try:
        s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = repr(obj)
    return _truncate(s, limit)


def record(trace_id: str, task_id: str, node_name: str, *,
           input_hash: str = "", output: Any = "", tokens: int = 0,
           latency_ms: float = 0, degraded: bool = False, degrade_reason: str = "",
           raw_response: str = "", finish_reason: str = ""):
    """写一条节点 Trace。任何异常都吞掉，不影响业务。"""
    if not _ENABLED:
        return
    try:
        database.insert_trace(
            trace_id=trace_id or "",
            task_id=task_id or "",
            node_name=node_name,
            input_hash=input_hash or "",
            output_json=dump(output),
            tokens=int(tokens or 0),
            latency_ms=int(round(latency_ms or 0)),
            degraded=bool(degraded),
            degrade_reason=degrade_reason or "",
            raw_response=_truncate(raw_response or "", MAX_RAW_RESPONSE),
            finish_reason=finish_reason or "",
        )
    except Exception as e:                      # pragma: no cover - 保护性兜底
        logger.warning("TRACE-WRITE-FAILED node=%s err=%r", node_name, e)
