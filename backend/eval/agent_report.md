# Agent 子模块报告（A1–A8）

> 执行书：《RAG 子模块 + Agent 子模块执行书》第二部分。
> 纪律：主干 4 步 Workflow 不改；只加分支；一次只改一个变量；每加一块跑一次基线；完成一项汇报一项。

## 一、加了什么

在 `parse_jd` 之后、`match_resume` 之前插入**条件分支**：JD 信息不足时向 HR 追问，信息充足时主链路一字不变。

```
parse_jd
   ↓
[Agent 子模块]  ← 新增
   ├─ 信息充足 → 继续主链路（match → questions → recommendation）
   └─ 信息不足 → 生成 1–3 条追问并返回（不跑匹配/面试题，0 次 LLM）
```

| 项 | 落点 | 做什么 |
|---|---|---|
| A1 | `app/database.py`（`ask_sessions` 表 + 3 个函数）、`app/main.py` | 用 `session_id` 挂载追问状态并可查询：`GET /api/agent/session/{id}` |
| A2 | `app/ask.py` | 信息充分性判定（纯规则、零 LLM）：技能信号 / 职责 / 经验年限 / 学历 |
| A3 | `app/ask.py` | 追问生成：四个信号 ↔ 四个模板，优先级 技能→经验→学历→职责，上限 3 条 |
| A4 | `app/agent.py`、`app/main.py` | `/analyze` 新增 `answers`；补充信息**累积合并**进 JD 后重新 `parse_jd`，只重走 parse 之后的链路 |
| A5 | `app/agent.py` | 追问上限 2 轮；超限转"待定"人工复核；无死循环 |
| A6 | `eval/eval_set_v1_2.jsonl`、`eval/build_eval_set_v1_2.py` | 评测集新增 10 条信息不足用例（带 `expected_status`），原 200 条逐字不动 |

状态机（`ask_sessions`）：`round`（已追问轮数）/ `status`（idle→insufficient→done / closed）/
`pending_questions`（待回答的追问）/ `merged_jd`（累积合并后的 JD）。

## 二、追问样例（真实生成，零 LLM）

| 输入 JD | 判定 | 生成的追问 |
|---|---|---|
| `招个前端` | insufficient | 「前端工程师」这个岗位的必须技能有哪些？／主要负责什么？ |
| `招聘后端工程师，要求有良好的沟通能力和团队协作精神` | insufficient | 必须技能有哪些？／主要负责什么？ |
| `招聘算法工程师（要求面议）` | insufficient | 必须技能有哪些？／主要负责什么？ |
| `招聘测试工程师，要求熟悉自动化测试与 Selenium，了解 JMeter` | **sufficient** | —（写了技能，只是词表没覆盖，**不误追问**）|
| `招聘 Java 后端工程师…精通 Java、Spring Boot，3 年经验，本科` | **sufficient** | —（信息充足，走主链路）|

## 三、改善幅度（A7 对比，评测集 v1_2 = 原有 200 + 新增 10）

| 指标 | ASK_ENABLED=0（前）| ASK_ENABLED=1（后）|
|---|---|---|
| 结论一致率 | 0.8182（171/209）| **0.823（172/209）** |
| 追问命中率（10 条新用例）| 0/10 | **10/10 = 1.0** |
| 追问条数 | — | 2（要求 1–3）|
| 分支 LLM 调用 | 0 | **0** |
| 错误数 | 0 | 0 |
| 结论变化用例 | — | 1 条（**由错变对 1 / 由对变错 0**）|
| 追问轮数上限 | — | 2（第 3 次仍无效 → `insufficient_final`）|
| 死循环 | 无 | 无（序列 `[1, 2, 2]`）|

**追问闭环的真实改善**（同一 `session_id`）：

```
第 1 次：JD「招聘后端工程师」→ 待定（信息不足，返回 2 条追问，0 次 LLM）
   ↓ HR 补充：必须技能=Java/Spring Boot/MySQL；经验=3 年以上；学历=本科及以上
第 2 次：→ 推荐（score 0 → 100，1 次 LLM，正常走主链路）
```

数据：`eval/agent_ab_table.md`、`eval/agent_ab_result.json`（脚本 `python eval/agent_ab.py`）。

## 四、边界处理

1. **轮数上限**：最多追问 2 轮；第 3 次补充仍无效 → `insufficient_final` + 结论"待定"（转人工复核），
   0 次 LLM，无死循环（`test_agent_ask_flow.py` 的 C 段与 `agent_ab.py` 的序列证据双重锁定）。
2. **对照组开关**：`ASK_ENABLED=0` 时完全不进分支，行为与加 Agent 之前**逐条一致**（0 变化）。
3. **信息充足的 JD**：响应字段结构不变、无 `ask` 字段（测试 E 锁死）。
4. **只占位不消耗**：分支返回前不调 LLM，也不跑匹配；`llm_calls=0`、`total_tokens=0`。
5. **判定口径校准（三次迭代，全部有数据支撑）**：
   - 字面规则（`required_skills` 为空即不足）在 200 条上判 7 条，其中 `E056` 明显写了技能却被误判 →
     加入"技能性表述"信号消歧 → **6 条**；
   - 造 A6 用例时又撞出两个假阴性：`要求有良好的沟通能力`（只有软技能）、`要求面议` →
     收紧为"表述里必须真的出现技能（ASCII 技术词 或 词表中文技能）"→ 两例均正确判不足，
     且 200 条校准数字与 A2 测试**完全不变**。

## 五、纪律执行记录（本轮真正拦住问题的地方）

| 事件 | 发现方式 | 处置 |
|---|---|---|
| **状态机 bug**：不带 `answers` 的请求也复用会话 `merged_jd`，跑批时 JD 互相覆盖，一致率 0.8141 → **0.3216** | 接线后例行跑基线 | 改为"只有带 answers 才复用"，恢复 0 漂移 |
| `rag_compare` 逐条统计用错键（`actual/expected` vs `pred_conclusion/gt_conclusion`），指标变了却报"0 条变化" | 对比基线时发现数字自相矛盾 | 修正键名并加"由对变错/由错变对"分类 |
| 评测把 `ask_sessions` 写脏（200 条共用 `session_id=default`）| DB 行数检查 | `eval_runner` 屏蔽 session 写入 |
| A2 规则两个假阴性（软技能、面议）| 设计 A6 用例 | 收紧技能信号口径，回归不变 |

数据库始终干净：`execution_history=31 / trace_events=4 / ask_sessions=0`（测试只删自己创建的行）。

## 六、局限与下一步

1. **前端未接**：追问通过 API 返回（`status=need_more_info` + `ask.questions`），前端还没有"展示追问 → 填写 → 提交 `answers`"的 UI；
   结果页会把这类响应显示为"待定"（不会崩，但 HR 看不到追问）。
2. **只接了 `/analyze`**：旧版 SSE `/api/agent/run` 未接分支（该链路已标注"新页面不使用"）。
3. **追问模板化**：四个信号 ↔ 四个模板 1:1 覆盖，未引入 LLM 改写；若要更贴合业务话术可加 LLM 兜底（当前刻意不加，避免成本）。
4. **`ROUND_LIMIT` 硬编码 2**：可提到配置项并透出到响应（现在响应里已带 `round_limit`）。
5. **会话无过期策略**：`ask_sessions` 没有 TTL 清理，长期运行需要加定期清理（与 `execution_history` 一起治理）。
6. 可观测：分支已写 `ask_branch` 节点 Trace；可再加聚合指标（追问率、平均轮数、补充后改善率）。
