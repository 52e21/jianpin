import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .agent import run_agent_with_history, analyze_agent
from .database import (init_db, fetch_history, delete_history, clear_history,
                       set_feedback, fetch_history_by_task, fetch_ask_session)
from .upload import MAX_FILE_SIZE, extract_resume

# 第 7 步：反馈接口的受控词表（避免脏数据进库）
FEEDBACK_ACTIONS = ("采纳", "改判", "反馈")
CONCLUSIONS = ("推荐", "待定", "不推荐")
# 第 10 步：角色视角（HR / 候选人）
ROLES = ("hr", "candidate")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库表
    init_db()
    # R6：后台预热 RAG 检索栈（模型加载 + 建索引约 20s），不阻塞启动、失败静默
    from .rag import warmup
    warmup()
    yield


app = FastAPI(title="简聘 Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3015",
        "http://127.0.0.1:3015",
        "http://localhost:3016",
        "http://127.0.0.1:3016",
        "http://4b24096f.r35.cpolar.top",
        "https://4b24096f.r35.cpolar.top",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/api/agent/history")
def agent_history(limit: int = 20, offset: int = 0):
    records, total = fetch_history(limit, offset)
    return {"records": records, "total": total}


@app.delete("/api/agent/history/{history_id}")
def delete_history_item(history_id: int):
    """删除单条历史记录。"""
    if not delete_history(history_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"message": "已删除"}


@app.delete("/api/agent/history")
def clear_history_items():
    """清空全部历史记录。"""
    deleted = clear_history()
    return {"message": "已清空", "deleted": deleted}


@app.post("/api/upload/resume")
async def upload_resume(file: UploadFile = File(...)):
    """接收简历文件（PDF/DOCX），返回提取的文本。纯本地处理，零 LLM。"""
    if file.size is not None and file.size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件过大，最大 5MB")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件过大，最大 5MB")
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    text = extract_resume(file.filename or "", content)
    if not text:
        raise HTTPException(status_code=400, detail="未能从文件中提取到文字（可能为扫描件/图片型 PDF）")
    return {"text": text, "filename": file.filename, "chars": len(text)}


@app.post("/api/agent/analyze")
async def agent_analyze(payload: dict):
    """结构化分析接口：同步返回 JSON（非 SSE），供秒悟新前端结果页使用。"""
    jd = (payload.get("jd") or "").strip()
    resume = (payload.get("resume") or "").strip()
    job_url = (payload.get("job_url") or "").strip()
    if not jd or not resume:
        raise HTTPException(status_code=400, detail="JD 与候选人简历都不能为空")
    # 第 9 步：缓存按租户/会话隔离（缺省 default；等接入登录体系后换成真实租户）
    tenant_id = (payload.get("tenant_id") or "default").strip() or "default"
    session_id = (payload.get("session_id") or "default").strip() or "default"
    # 第 10 步：角色（hr / candidate）；非法值直接 400，避免脏值进缓存 key
    role = (payload.get("role") or "hr").strip() or "hr"
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="role 必须是 " + " / ".join(ROLES) + " 之一")
    return await analyze_agent(jd, resume, job_url,
                               tenant_id=tenant_id, session_id=session_id, role=role)


@app.post("/api/agent/feedback")
def agent_feedback(payload: dict):
    """第 7 步：记录用户对分析结论的反馈。

    入参：
        { "task_id": "tk_xxx", "action": "采纳|改判|反馈",
          "new_conclusion": "推荐|待定|不推荐"（仅 action=改判 时必填）,
          "comment": "可选" }
    落库：execution_history.feedback（JSON 字符串） + feedback_at（时间戳）
    """
    task_id = (payload.get("task_id") or "").strip()
    action = (payload.get("action") or "").strip()
    new_conclusion = (payload.get("new_conclusion") or "").strip()
    comment = (payload.get("comment") or "").strip()

    if not task_id:
        raise HTTPException(status_code=400, detail="task_id 不能为空")
    if action not in FEEDBACK_ACTIONS:
        raise HTTPException(status_code=400, detail="action 必须是 " + " / ".join(FEEDBACK_ACTIONS) + " 之一")
    if action == "改判":
        if new_conclusion not in CONCLUSIONS:
            raise HTTPException(status_code=400, detail="改判时必须提供合法的 new_conclusion（推荐/待定/不推荐）")
    else:
        new_conclusion = ""

    record = fetch_history_by_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="未找到该 task_id 对应的分析记录")

    feedback = json.dumps(
        {"action": action, "new_conclusion": new_conclusion, "comment": comment,
         "original_conclusion": _extract_conclusion(record.get("result", ""))},
        ensure_ascii=False,
    )
    res = set_feedback(task_id, feedback)
    if not res.get("updated"):
        raise HTTPException(status_code=404, detail="未找到该 task_id 对应的分析记录")

    return {
        "message": "已记录",
        "task_id": task_id,
        "action": action,
        "new_conclusion": new_conclusion,
        "original_conclusion": _extract_conclusion(record.get("result", "")),
        "feedback_at": res["feedback_at"],
    }


def _extract_conclusion(result_text: str) -> str:
    """从历史 result 文本里取出原结论（用于计算改判方向）。"""
    for c in CONCLUSIONS:
        if f"结论：{c}" in (result_text or ""):
            return c
    return ""


@app.get("/api/agent/session/{session_id}")
def agent_session(session_id: str):
    """A1（Agent 子模块）：查询某个 session 挂载的追问状态。

    同一 session_id 的多次 /analyze 共享这份状态：追问轮数（round，上限 2）、
    待回答的追问（pending_questions）、以及 A4 合并后的 JD（merged_jd）。
    不回传 JD/简历全文，只给长度与预览（避免把用户输入再吐一遍）。
    """
    rec = fetch_ask_session(session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="该 session_id 未挂载任何状态")

    pending = rec.get("pending_questions") or ""
    try:
        pending_obj = json.loads(pending) if pending else []
    except Exception:
        pending_obj = pending
    return {
        "session_id": rec.get("session_id"),
        "tenant_id": rec.get("tenant_id"),
        "role": rec.get("role"),
        "round": rec.get("round", 0),
        "status": rec.get("status", "idle"),
        "round_limit": 2,
        "pending_questions": pending_obj,
        "merged_jd_chars": len(rec.get("merged_jd") or ""),
        "jd_chars": len(rec.get("jd") or ""),
        "resume_chars": len(rec.get("resume") or ""),
        "jd_preview": (rec.get("jd") or "")[:40],
        "created_at": rec.get("created_at"),
        "updated_at": rec.get("updated_at"),
    }


@app.post("/api/agent/run")
async def agent_run(payload: dict):
    jd = (payload.get("jd") or "").strip()
    resume = (payload.get("resume") or "").strip()
    if not jd or not resume:
        return {"error": "JD 与候选人简历都不能为空"}
    # 第 9 步：缓存按租户/会话隔离
    tenant_id = (payload.get("tenant_id") or "default").strip() or "default"
    session_id = (payload.get("session_id") or "default").strip() or "default"
    # 第 10 步：角色
    role = (payload.get("role") or "hr").strip() or "hr"
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="role 必须是 " + " / ".join(ROLES) + " 之一")

    async def event_generator():
        async for chunk in run_agent_with_history(jd, resume, tenant_id, session_id, role):
            yield {"data": chunk}

    return EventSourceResponse(event_generator())
