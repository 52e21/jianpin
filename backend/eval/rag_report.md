# RAG 子模块报告（R1–R8）

> 执行书：《RAG 子模块 + Agent 子模块执行书》第一部分。
> 纪律：主干 4 步 Workflow 不改；RAG 是**只读增强**；一次只改一个变量；每加一块跑一次基线。

## 一、加了什么

在 `parse_jd` 与 `match_resume` 之间插入**只读检索层**，检索结果**只注入 `generate_interview_questions`**，
不注入 `match_resume`（匹配打分必须可复现）。落点全部在 `backend/app/rag/` 下：

| 项 | 文件 | 做什么 |
|---|---|---|
| R1 | `app/rag/knowledge/capability_models.jsonl` | 20 条岗位能力模型（`id/role/skill/capability/source`），手工构造 |
| R2 | `app/rag/chunker.py` | 结构分块：1 条能力 = 1 chunk；仅当 >500 字才按 段落→句子→分句 逐级聚合，**不做定长硬切** |
| R3 | `app/rag/embedder.py` | 中文检索模型 `BAAI/bge-small-zh-v1.5` 编码（512 维、归一化、可落盘复现）；query 侧加 bge 官方检索前缀 |
| R4 | `app/rag/store.py` | Chroma 持久化集合（cosine + metadata 过滤），关闭匿名遥测 |
| R5 | `app/rag/retriever.py` | 混合检索：向量 Top20 + 关键词 Top20 → **RRF 融合**（k=60）→ Top3–5；无重排 |
| R6 | `app/rag/inject.py` + `app/tools.py` + `app/agent.py` | 把检索块拼进面试题生成 prompt（≤5 条 / ≤400 字），并在启动时后台预热 |
| 降级 | `app/rag/fallback.py` | 依赖缺失时的零依赖兜底（TF-IDF 稀疏向量 + 内存向量库），`get_searcher()` 如实标注当前后端 |

关键设计决策：
1. **关键词侧复用主链路口径**（`app.tools._norm_skill` / `_token_hits` / 别名表），保证 "Java" 不会命中 "JavaScript"。
2. **RRF 而非加权求和**：两路分数尺度不同，排序融合更稳。
3. **注入可降级**：检索异常 / 为空 / `RAG_ENABLED=0` 时，prompt 与加 RAG 之前**逐字一致**。
4. **进程内单例 + 启动预热**：冷启动 22s 不落在第一个用户请求上。

## 二、检索样例（真实输出）

**1) 技能查询**（关键词侧精确命中）

| 查询 | Top 结果 |
|---|---|
| `['Java','Spring Boot','MySQL','Redis']` | cap_001 Java、cap_002 Spring Boot、cap_004 MySQL、cap_005 Redis（各 3.0 分，metadata 精确命中）|
| `['k8s']` | cap_008 **Kubernetes**（别名表生效）|

**2) 语义查询**（关键词做不到的部分 —— 向量侧的证明）

| 查询 | Chroma+bge Top3（cosine 距离）|
|---|---|
| `服务端并发与连接池`（**不含任何技能名**）| cap_007 **Go** 0.527 / cap_015 Flink 0.587 / cap_001 Java 0.596 |

**3) 注入块实际形态**（`RAG_ENABLED=1`，技能 = Java/Spring Boot/MySQL/Redis/消息队列）

```
岗位能力参考：
- Java：熟悉 JVM 内存结构与 GC、并发包（JUC）；…
- Spring Boot：能独立搭建 REST 服务；理解 IoC/AOP、自动配置与 Starter 机制，…
- MySQL：能设计规范化表结构与索引（B+ 树、最左前缀、覆盖索引）；…
```

## 三、加 RAG 前后对比

### 3.1 结论一致率（LLM-off 全量 200 条，规则路径）

RAG 接线**没有触碰** `parse_jd` / `match_resume` / 推荐阈值，因此规则路径必须零漂移：

| 指标 | 加 RAG 前 | 加 RAG 后 |
|---|---|---|
| 结论一致率 | 0.8141（162/199）| **0.8141（162/199）** |
| 必须技能 P/R | 0.7498 / 0.9802 | **0.7498 / 0.9802** |
| 全部技能 P/R | 0.9107 / 0.9832 | **0.9107 / 0.9832** |
| 错误数 | 0 | **0** |
| 逐条结论变化 | — | **0 条** |

> 数据：`eval/rag_before_baseline.json`（before，已提交）vs `eval/rag_after_r6.json`（after）。
> 对比工具：`python eval/rag_compare.py <before.json> <after.json> [--out 表.md]`。

### 3.2 面试题相关性 / token / 延迟（LLM-on 小样本 A/B）

同一批 10 条用例（E001/E002/E004/E005/E006/E008/E009/E010/E011/E012），两组用不同 `session_id` 规避结果缓存；
两组各 1 次生成 + 1 次 **LLM 盲评**（评委不知道哪组加了 RAG）。

**第 1 轮**（`eval/rag_ab_table_run1.md`）：

| 指标 | 加 RAG 前 | 加 RAG 后 | 变化 |
|---|---|---|---|
| 题目覆盖"检索到的岗位能力点"率 | 0.4000 | **0.7400** | **+0.3400** |
| 题目覆盖 JD 必须技能率 | 0.9750 | **1.0000** | +0.0250 |
| 题目不重复度 | 0.9455 | 0.9588 | +0.0134 |
| 平均 tokens | 1333.4 | 1744.8 | **+411.4（+31%）** |
| P50 延迟(ms) | 7025.9 | 8315.8 | +1290（+18%） |
| P95 延迟(ms) | 8003.0 | 10224.8 | **+2222（+28%）** |
| LLM 调用次数 | 13 | 13 | ±0 |
| LLM 盲评均分(0-10) | 7.50 | 6.70 | **−0.80**（σ=1.33，n=10，SE≈0.42 → **未达显著**）|

结论（如实）：
- **面试题相关性：从"是否用上检索知识"看是提升**（能力点覆盖 0.40 → 0.74，JD 技能覆盖 1.00），
  这是 RAG 起作用的最直接证据；
- **从 LLM 盲评看是"未定"**：−0.8 分在噪声范围内（逐条 1 升 4 平 5 降），已启动第 2 轮同条件实验，
  两轮合并 n=20 再判定；
- **成本上升是确定性的**：token **+31%**、P95 **+28%**（每一条用例的 token 都上升）。
  优化方向：注入条数 5 → 3，或只注入 JD 必须技能命中的能力点。
- 判定口径修正记录：首轮 `_mentioned()` 漏了 `.lower()`，导致覆盖度被严重低估（曾显示 0/5）；
  修正后用同一批已保存的题目重算，无需重跑 LLM。这一条也说明**自动指标必须自检**。

## 四、失败案例与局限（如实登记）

1. **外网模型源全部不可达**：`huggingface.co` / `hf-mirror.com` / `modelscope.cn` 均连接失败（curl `000`）。
   因此 R3 只能用**本地缓存快照**：把 `bge-small-zh-v1.5` 拷进 `backend/.models/`（本地忽略），
   `embedder.get_model()` 优先加载本地目录。换模型必须先离线准备好。
2. **沙箱内 `pip` 不可用**：pip 写临时目录被文件权限拒绝（`PermissionError`），依赖只能由使用者在自己的终端安装。
   已装：torch 2.14.0 / sentence-transformers 6.0.1 / chromadb 1.5.9 / onnxruntime 1.30.0 / numpy 2.5.3。
3. **知识源覆盖 81.3%**：评测集有 35 个 distinct 必须技能，20 条能力模型按出现频次加权覆盖 305/375。
   未覆盖主要是 `Kafka`（我用"消息队列"作 skill 名，**语义覆盖但关键词不命中**）、`Flask`、`Python`、`FastAPI`、
   `项目管理`、`爬虫`、`Docker`。执行书固定 20 条，故未扩表；扩表是低风险下一步。
4. **RRF 默认 k=60、无重排**：按执行书要求先不做 rerank；Top3–5 的相关性依赖两路召回质量。
5. **生成侧噪声**：面试题生成 `temperature=0.5`，A/B 两次生成不完全可比，因此除 LLM 盲评外，
   还统计了确定性指标（JD 技能覆盖率、能力点覆盖率、题目不重复度）。
6. **兜底实现不是语义模型**：`fallback.py` 的 TF-IDF 只在依赖缺失时生效，用于保证 R3/R4/R5 的验收
   *行为* 仍可测量；它不是 bge 的替代品，`get_searcher().name` 会如实暴露当前后端。

## 五、下一步

1. 进入**第二部分：Agent 子模块**（A1–A8）：`session_id` 挂载追问状态 → 信息不足规则判定 →
   追问生成 → 补充后重走 `parse_jd` 之后链路 → 最多 2 轮边界 → 10 条用例 → 对比 → 报告。
2. RAG 侧可选增强（按收益排序）：知识源扩到 25–30 条补上 `Python/Flask/FastAPI/Kafka/Axure` 等；
   引入 rerank（bge-reranker）；把 `rag_chars/rag_chunk_ids/rag_modes` 写进 Trace 便于线上归因。
