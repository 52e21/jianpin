# 简聘 - 技术文档

## 项目概述
简聘是一款面向 HR 和招聘团队的智能招聘辅助工具，通过 AI 技术自动完成岗位 JD 解析、候选人简历匹配、面试题生成与推荐结论汇总。

## 架构原则
**前端只负责展示与调用后端接口；所有解析、匹配、缓存与成本控制逻辑均在后端（FastAPI）实现，前端不做任何本地规则计算。**

## 技术栈
- **框架**: React 19 + Vite + TypeScript
- **路由**: TanStack Router（页面间通过路由 state 传递数据）
- **样式**: Tailwind CSS v4 + shadcn/ui
- **本地状态**: React Hooks + sessionStorage（结果页持久化，跳详情页返回不丢）

## 数据流

```
首页 / → 输入页 /match → POST /api/agent/analyze → 结果页 /result（sessionStorage 持久化）
                                                    ├─ 面试题详情 /interview/$id（路由 state 传题）
                                                    └─ 历史记录 /history（调后端历史接口）
```

## 后端接口依赖（前端侧）

| 用途 | 接口 |
|---|---|
| 结构化分析（结果页数据源） | `POST /api/agent/analyze` 返回 `{jd_parse, match_result, interview_questions, recommendation, llm_calls, total_tokens, cache_hit}` |
| 追问分支（JD 信息不足时） | 同一个 `POST /api/agent/analyze`，返回 `{status: "need_more_info", ask: {questions, round, round_limit}}`（`match_result` 为 null、零 LLM）；HR 填写后带 `answers: [{question, answer}]` 重新请求**同一 session_id** |
| 追问状态查询（可选） | `GET /api/agent/session/{session_id}` → `{round, status, pending_questions, ...}` |
| 简历文件上传 | `POST /api/upload/resume`（PDF/DOCX，返回提取文本） |
| 历史记录（分页） | `GET /api/agent/history?limit=&offset=` 返回 `{records, total}` |
| 删除单条 | `DELETE /api/agent/history/{id}` |
| 清空全部 | `DELETE /api/agent/history` |

注意：旧版 SSE 接口 `POST /api/agent/run` 为兼容保留，**新页面不使用**；结果页一律走 `/api/agent/analyze` 结构化 JSON。

## 页面路由（5 页）
- `/` 首页：静态落地页，"开始匹配"跳 /match
- `/match` 输入页：JD + 简历双文本区 + 文件上传 + "填入示例"（示例常量内联于 match.tsx）
- `/result` 结果页：环形匹配度、五维得分、技能标签、面试题列表、推荐结论（绿/黄/红）；数据来自 analyze 响应并经 `sessionStorage("lastAnalyzeResult")` 持久化。
  **当响应带 `status=need_more_info` 时改为渲染追问卡片**（此时没有 match_result，不能走打分渲染）；
  追问续接所需的原始 JD/简历存于 `sessionStorage("lastAnalyzeInput")`（route state 优先）。
- `/interview/$id` 面试题详情：展示题目、类别、难度、参考答案要点、评分标准（数据经路由 state 传入）
- `/history` 历史记录：后端分页 + 本地搜索过滤 + 删除/清空（弹窗确认）

## 组件清单
- CircularProgress: 环形进度条，颜色随分数变化
- SkillTag/SkillTagGroup: 技能标签（必须/优先/命中/缺失）
- ResultCard/StatusCard: 结果展示卡片（推荐绿/待定黄/不推荐红）
- FileUpload: 文件上传组件（调后端提取）
- AskCard: 追问卡片（JD 信息不足时展示 1–3 个问题 + 输入框 + "提交补充并重新匹配"）
- Navbar/Footer: 布局组件

## 设计系统
- 主色调: 科技蓝 (oklch 蓝色系)
- 状态色: 绿色(推荐)、黄色(待定)、红色(不推荐)
- 动画: reveal 滚动渐入、卡片悬停效果

## 成本控制（后端职责，前端感知）
- 低匹配(<50%)零 LLM：后端短路，`interview_questions` 为空、结论"不推荐"
- 解析/匹配纯规则零 LLM；仅"面试题生成 + 待定结论"调 LLM（上限 2 次）
- 相同 JD+简历 10 分钟内缓存命中，响应含 `cache_hit: true`

## 修改提示
- 新增/调整页面时保持"纯 API 调用"，勿在前端引入本地解析/匹配逻辑。
- 面试题数据结构含 `category / difficulty / question / answer_points / scoring_criteria`（后端 LLM 生成）。
- 结果页数据恢复顺序：路由 state（新匹配）→ sessionStorage（详情页返回）；"重新匹配"会清除 sessionStorage。
