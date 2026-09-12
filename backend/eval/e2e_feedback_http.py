# -*- coding: utf-8 -*-
"""
事项 5（第 8 步前端点击验证）· 沙箱内可执行的最强替代验证

背景：浏览器点击无法在本沙箱完成 —— Chrome 依赖 mojo 命名管道，
      被沙箱拒绝（FATAL: platform_channel.cc Check failed 拒绝访问），
      `--single-process` 也绕不开，DevTools 端口只存活一瞬。

因此本脚本做两件能做的事，并**明确标注它证明了什么、没证明什么**：
  A. 契约静态核对：从 feedback-bar.tsx 源码提取组件真正发出去的 JSON 字段，
     校验它与后端接口字段逐一对齐（防"前端改字段名、后端收不到"）
  B. 接口级端到端：用真实 HTTP 以**同一份字段结构**打一遍 analyze → feedback，
     并校验 execution_history 里确实写入了 feedback / feedback_at

用法：
    先启动后端（如 127.0.0.1:8014），再 python eval/e2e_feedback_http.py
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "frontend"
BASE = "http://127.0.0.1:8014"
DB = BACKEND / "data" / "history.db"


def extract_fields():
    """从组件源码提取它真正发出去的 JSON 字段。

    注意：必须支持 ES6 **简写属性**（源码里是 `action,` 而不是 `action: action,`），
    只匹配 `key:` 会漏掉 action —— 我第一版就这么漏了。
    """
    src = (FRONTEND / "src" / "components" / "feedback-bar.tsx").read_text(encoding="utf-8")
    body = re.search(r"JSON\.stringify\(\{(.*?)\}\)", src, re.S)
    keys = set()
    if body:
        for part in body.group(1).split(","):
            m = re.match(r"\s*([A-Za-z_]\w*)", part)
            if m:
                keys.add(m.group(1))
    url = re.search(r"fetch\(`\$\{API_BASE\}([^`]+)`", src)
    return keys, (url.group(1) if url else ""), src


def part_a():
    print("=== A. 契约静态核对（组件真正发出去的字段 vs 后端接收字段）===")
    keys, path, src = extract_fields()
    expect = {"task_id", "action", "new_conclusion", "comment"}
    print(f"  feedback-bar.tsx 发送字段: {sorted(keys)}")
    print(f"  调用路径: {path}")

    main_src = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    result_src = (FRONTEND / "src" / "routes" / "result.tsx").read_text(encoding="utf-8")
    checks = [
        (keys == expect, f"字段与接口完全对齐（期望 {sorted(expect)}）"),
        (bool(path) and path in main_src, "路径与后端一致"),
        ("FeedbackBar taskId={data.task_id}" in result_src, "结果页已挂载并传入 task_id"),
    ]
    for good, desc in checks:
        print(f"  {'OK  ' if good else 'FAIL'} {desc}")
    return all(g for g, _ in checks), keys


def part_b(fields):
    """用**组件真正发出的字段名**构造请求，走真实 HTTP，校验落库。"""
    print("\n=== B. 接口级端到端（真实 HTTP，字段名取自组件源码）===")
    import time
    values = {"task_id": "", "action": "改判", "new_conclusion": "待定", "comment": "接口级验证"}
    c = httpx.Client(timeout=120)
    # 用唯一 session 避免命中上一次的缓存（否则会拿到旧 task_id，干扰验证）
    sid = f"e2e-{int(time.time())}"
    r = c.post(f"{BASE}/api/agent/analyze", json={
        "jd": "招聘Java开发工程师，要求精通Java与SpringBoot。",
        "resume": "候选人，3年Java经验，精通Java与SpringBoot。",
        "tenant_id": "e2e", "session_id": sid, "role": "hr"})
    print(f"  analyze HTTP={r.status_code}  cache_hit={r.json().get('cache_hit') if r.status_code == 200 else '-'}")
    if r.status_code != 200:
        print(f"  FAIL: {r.text[:200]}")
        return False
    d = r.json()
    task_id = d["task_id"]
    print(f"  task_id={task_id}  结论={d['recommendation']['type']}  文案={d['recommendation'].get('label')}")

    values["task_id"] = task_id
    fb = {k: values[k] for k in fields}          # 字段名来自源码，不手写
    print(f"  提交 payload 字段: {sorted(fb.keys())}")
    resp = c.post(f"{BASE}/api/agent/feedback", json=fb)
    print(f"  feedback HTTP={resp.status_code} body={resp.json()}")

    con = sqlite3.connect(DB)
    row = con.execute("SELECT task_id, feedback, feedback_at FROM execution_history "
                      "WHERE task_id=?", (task_id,)).fetchone()
    print(f"  落库 feedback={row[1] if row else None}")
    print(f"        feedback_at={row[2] if row else None}")
    got = json.loads(row[1]) if row and row[1] else {}
    ok = (resp.status_code == 200 and row is not None and got.get("action") == "改判"
          and got.get("new_conclusion") == "待定" and bool(row[2]))
    print(f"  B 结果: {'PASS' if ok else 'FAIL'}")
    con.execute("DELETE FROM execution_history WHERE task_id=?", (task_id,))
    con.execute("DELETE FROM trace_events WHERE task_id=?", (task_id,))
    con.commit()
    print(f"  已清理测试数据: {con.execute('SELECT count(*) FROM execution_history WHERE task_id=?', (task_id,)).fetchone()[0] == 0}")
    return ok


if __name__ == "__main__":
    a, fields = part_a()
    b = part_b(fields)
    print("\n" + "=" * 70)
    print("总结果:", "全部通过 ✅" if (a and b) else "存在失败 ❌")
    print("""
【本验证证明了什么】
  ✅ 前端组件发出的字段/路径与后端接口逐一对齐
  ✅ 结果页确实把 task_id 传给了反馈组件
  ✅ 用同一份字段结构走真实 HTTP，能成功写入 execution_history.feedback / feedback_at

【本验证没证明什么】（沙箱限制，需人工点击确认）
  ❌ React 事件绑定是否真的被触发（按钮点击 → submit() 调用）
       —— 这需要浏览器，而 Chrome 依赖 mojo 命名管道，被本沙箱拒绝
""")
    sys.exit(0 if (a and b) else 1)
