# -*- coding: utf-8 -*-
"""RAG 子模块（只读增强，不改主链路决策）。

R1 知识源: knowledge/capability_models.jsonl
R2 分块  : chunker.py
R3 向量化: embedder.py
R4 向量库: store.py
R5 检索  : retriever.py（向量 TopN + 关键词 TopN → RRF → TopK）
R6 注入  : inject.py（只注入面试题生成；本模块的 warmup 用于启动预热）
"""


def warmup(background: bool = True) -> None:
    """预热检索栈：加载中文模型 + 建立/校验向量索引（实测冷启动约 20s）。

    不预热的话，第一个用户请求会额外背这段耗时。这里默认用**后台守护线程**，
    失败或依赖缺失一律静默跳过，绝不影响应用启动。
    开关：RAG_ENABLED=0 或 RAG_WARMUP=0 时跳过。
    """
    import os
    import threading
    import time

    if os.environ.get("RAG_ENABLED", "1") == "0" or os.environ.get("RAG_WARMUP", "1") == "0":
        return

    def _run():
        t0 = time.perf_counter()
        try:
            from .inject import capability_context_for_skills

            out = capability_context_for_skills(["预热"])
            print("[rag] warmup done in %.0f ms (modes=%s)" % (
                (time.perf_counter() - t0) * 1000, out.get("modes")), flush=True)
        except Exception as e:                     # 依赖缺失/模型不可用 → 静默跳过
            print("[rag] warmup skipped: %s: %s" % (type(e).__name__, str(e)[:80]), flush=True)

    if background:
        threading.Thread(target=_run, name="rag-warmup", daemon=True).start()
    else:
        _run()
