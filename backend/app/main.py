from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .agent import run_agent_with_history, analyze_agent
from .database import init_db, fetch_history, delete_history, clear_history
from .upload import MAX_FILE_SIZE, extract_resume


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库表
    init_db()
    yield


app = FastAPI(title="简聘 Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3015",
        "http://127.0.0.1:3015",
        "http://6f2abf86.r35.cpolar.top",
        "https://6f2abf86.r35.cpolar.top",
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
    return await analyze_agent(jd, resume, job_url)


@app.post("/api/agent/run")
async def agent_run(payload: dict):
    jd = (payload.get("jd") or "").strip()
    resume = (payload.get("resume") or "").strip()
    if not jd or not resume:
        return {"error": "JD 与候选人简历都不能为空"}

    async def event_generator():
        async for chunk in run_agent_with_history(jd, resume):
            yield {"data": chunk}

    return EventSourceResponse(event_generator())
