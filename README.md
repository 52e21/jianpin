# 简聘

AI 驱动的智能招聘匹配系统：输入岗位 JD 与候选人简历，自动完成 JD 解析、简历匹配、面试题生成与推荐结论。

## 架构

- 后端：FastAPI + DeepSeek + SQLite（解析/匹配纯规则零 LLM，面试题与待定结论按需调 LLM）
- 前端：React 19 + Vite 7 + TanStack Router + Tailwind CSS 4（秒悟设计，蓝/橙主色调）
- 端口：后端 8002 · 前端 3015

## 功能

- JD 八维解析：职位/部门/级别/职责/必须技能/优先技能/经验/学历/软技能/加分项/工作模式
- 简历加权匹配：技能 40% + 经验 25% + 学历 15% + 软技能 10% + 加分 10%（含否定语境检测、子串去重）
- 面试题生成：LLM 输出题目 + 类别 + 难度 + 参考答案要点 + 评分标准
- 推荐结论：匹配度 ≥80 且缺失 ≤1 → 推荐；<50 → 不推荐（均零 LLM）；中间地带调 LLM 定"待定"
- 简历文件上传：PDF/DOCX 本地提取（纯本地，零 LLM），限 5MB
- 历史记录：SQLite 分页存储、搜索、单条删除、清空
- 成本控制：缓存 TTL 600s、LLM 上限 2 次、低匹配短路

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 健康检查 |
| POST | `/api/agent/analyze` | 结构化分析（JSON，新前端结果页使用） |
| POST | `/api/agent/run` | SSE 流式执行（兼容旧前端） |
| POST | `/api/upload/resume` | 简历文件上传提取 |
| GET | `/api/agent/history?limit&offset` | 历史记录（分页，返回 total） |
| DELETE | `/api/agent/history/{id}` | 删除单条 |
| DELETE | `/api/agent/history` | 清空全部 |

## 启动

### 后端

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
# 复制 .env.example 为 .env 并填入 DEEPSEEK_API_KEY
.venv\Scripts\python -m uvicorn app.main:app --port 8002
```

### 前端

```powershell
cd frontend
npm install
npm run dev   # http://localhost:3015
```

## 目录结构

```
agent-assistant/
├── backend/
│   ├── app/
│   │   ├── main.py        # FastAPI 入口（analyze/run/upload/history）
│   │   ├── agent.py       # Agent 编排：规则路由 → 缓存 → LLM
│   │   ├── tools.py       # 解析/匹配/面试题/推荐 工具
│   │   ├── database.py    # SQLite 历史记录
│   │   ├── upload.py      # PDF/DOCX 简历提取
│   │   └── config.py      # 环境配置 + 成本控制参数
│   ├── data/              # SQLite 数据（不入 Git）
│   └── .env               # API Key（不入 Git）
├── frontend/
│   └── src/routes/        # 首页 / match / result / interview / history
└── README.md
```

## 测试场景

| 输入 | 预期 |
|---|---|
| Java 高匹配简历 | 匹配度 ≥80 → 推荐，生成面试题（LLM 1 次） |
| 前端低匹配简历（只会 Vue 不熟 React） | 匹配度 <50 → 不推荐，零 LLM，跳过面试题 |
| 相同 JD+简历重复提交 | 缓存命中秒回 |

## 说明

- 解析与匹配纯规则零 LLM；仅"面试题生成 + 待定结论"调 LLM（上限 2 次）。
- `.env` 与 `backend/data/` 为敏感/运行时文件，请勿提交到 Git。
