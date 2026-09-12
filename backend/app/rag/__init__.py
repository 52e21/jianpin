# -*- coding: utf-8 -*-
"""RAG 子模块（只读增强，不改主链路决策）。

R1 知识源: knowledge/capability_models.jsonl
R2 分块  : chunker.py
R3 向量化: embedder.py
R4 向量库: store.py
R5 检索  : retriever.py（向量 TopN + 关键词 TopN → RRF → TopK）
"""
