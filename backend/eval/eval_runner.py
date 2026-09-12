# -*- coding: utf-8 -*-
"""
第 2 步：评测跑批脚本 eval_runner.py

用法（在 agent-assistant/backend 目录下执行）：
    .venv\\Scripts\\python.exe eval\\eval_runner.py                    # 默认：关 LLM，跑规则链路，秒级
    .venv\\Scripts\\python.exe eval\\eval_runner.py --limit 8 --with-llm  # 小样本真实调 LLM
    .venv\\Scripts\\python.exe eval\\eval_runner.py --out eval\\baseline.json

输出指标：
    - 结论一致率（含混淆矩阵）
    - JD 技能 准确率 / 召回率 / F1（严格口径 + 宽松别名口径）
    - 平均 token
    - P50 / P95 延迟
    - 低分短路率（llm_calls == 0 的占比）、异常数、缓存命中数（应为 0，用于验证"关缓存"生效）

关键实现约定：
    - **关缓存**：每个用例前清空 agent._analyze_cache，保证 100% 未命中
    - **关 LLM**：把 app.config.DEEPSEEK_API_KEY 置空，两个 LLM 节点走各自的降级分支（确定性、零成本）
    - **不写业务库**：把 app.database.save_history 替换为 no-op，避免 200 条评测数据污染 execution_history
"""
import argparse
import json
import logging
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import app.agent as agent              # noqa: E402
import app.config as config            # noqa: E402
import app.database as database        # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_SET = EVAL_DIR / "eval_set_v1.jsonl"

# 关掉 agent 的逐条 INFO 日志：200 条跑批时它会向 stderr 刷屏（也会让 PowerShell 误判为错误输出）
logging.getLogger("agent").setLevel(logging.WARNING)

# 宽松口径的别名表（仅用于"宽松口径"指标；严格口径不改写任何技能名）
ALIASES = {
    "k8s": "kubernetes", "springboot": "spring boot", "vue.js": "vue",
    "js": "javascript", "ts": "typescript", "pg": "postgresql",
    "es": "elasticsearch", "ml": "machine learning",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def norm_loose(s: str) -> str:
    n = norm(s)
    return ALIASES.get(n, n)


def prf(pred: set, gt: set, key=norm):
    """返回 (precision, recall, f1)；两边都空时返回 None（无可评估内容）"""
    if not gt and not pred:
        return None
    tp = len({key(x) for x in pred} & {key(x) for x in gt})
    p = tp / len({key(x) for x in pred}) if pred else 0.0
    r = tp / len({key(x) for x in gt}) if gt else 0.0
    f = (2 * p * r / (p + r)) if (p + r) else 0.0
    return p, r, f


def pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def load_set(path: Path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def group_of(case) -> str:
    """用例分组 —— 决定"一致率"该按哪类口径解读：

    - template：模板生成，期望值天然由模板规则/规范阈值决定
                → 它只能验证「实现是否符合自己的规范」(conformance)
    - hand    ：人工设计的边界用例，期望值来自业务判断
    - real    ：真实历史输入 / 样本文件，期望值来自业务判断
    → hand + real 才是「业务一致性」；template 单独报，避免稀释或掩盖问题。
    """
    if case.get("group"):
        return case["group"]          # 用例自带分组（如 boundary 边界兜底）
    if case.get("source") == "constructed":
        return "template" if "模板生成" in (case.get("note") or "") else "hand"
    return "real"


GROUP_LABEL = {
    "template": "规范一致性（模板生成）",
    "hand": "业务一致性（人工设计边界）",
    "real": "业务一致性（真实输入/样本）",
    "boundary": "边界兜底（不计入一致率）",
}


async def run_one(case, with_llm: bool):
    """跑单条用例，返回结构化结果。"""
    agent._analyze_cache.clear()          # 关缓存：保证未命中
    jd, resume = case["jd"], case["resume"]
    t0 = time.perf_counter()
    err = ""
    payload = None
    try:
        payload = await agent.analyze_agent(jd, resume)
    except Exception as e:                # 评测必须容错，异常要计数而不是崩掉整批
        err = f"{type(e).__name__}: {e}"
    latency_ms = (time.perf_counter() - t0) * 1000
    if payload is None:
        return {"id": case["id"], "ok": False, "error": err, "latency_ms": latency_ms}

    jd_parse = payload.get("jd_parse", {}) or {}
    skills = jd_parse.get("skills", {}) or {}
    pred_req = list(skills.get("required", []) or [])
    pred_pref = list(skills.get("preferred", []) or [])
    pred_all = pred_req + pred_pref
    pred_concl = (payload.get("recommendation", {}) or {}).get("type", "")
    match = payload.get("match_result", {}) or {}

    return {
        "id": case["id"],
        "ok": True,
        "source": case["source"],
        "group": group_of(case),
        # 边界兜底用例（如空 JD）不计入一致率：它测的是接口层职责，见 contract_set_v1.jsonl
        "excluded": bool(case.get("exclude_from_agreement")),
        "error": "",
        "latency_ms": latency_ms,
        "tokens": payload.get("total_tokens", 0) or 0,
        "llm_calls": payload.get("llm_calls", 0) or 0,
        "cache_hit": bool(payload.get("cache_hit", False)),
        "pred_conclusion": pred_concl,
        "gt_conclusion": case["gt"]["conclusion"],
        "pred_required": pred_req,
        "pred_preferred": pred_pref,
        "pred_all": pred_all,
        "gt_required": case["gt"]["jd_required_skills"],
        "gt_all": case["gt"]["jd_required_skills"] + case["gt"]["jd_preferred_skills"],
        "match_score": match.get("score"),
        "needs_human_review": case.get("needs_human_review", False),
    }


def summarize(results, set_path: Path, with_llm: bool, elapsed_s: float):
    total = len(results)
    errors = [r for r in results if not r["ok"]]
    oks_all = [r for r in results if r["ok"]]
    # 边界兜底用例（exclude_from_agreement）不计入一致率与技能指标
    oks = [r for r in oks_all if not r.get("excluded")]
    excluded = [r for r in oks_all if r.get("excluded")]

    # ---- 结论一致率 ----
    agree = sum(1 for r in oks if r["pred_conclusion"] == r["gt_conclusion"])
    conf = defaultdict(Counter)
    for r in oks:
        conf[r["gt_conclusion"]][r["pred_conclusion"]] += 1

    # ---- 技能 P/R/F1（严格 + 宽松）----
    def agg(field_pred, field_gt, key, items=None):
        src = oks if items is None else items
        ps, rs, fs = [], [], []
        for r in src:
            v = prf(r[field_pred], r[field_gt], key=key)
            if v:
                ps.append(v[0]); rs.append(v[1]); fs.append(v[2])
        m = lambda a: (sum(a) / len(a)) if a else None
        return m(ps), m(rs), m(fs)

    all_strict = agg("pred_all", "gt_all", norm)
    all_loose = agg("pred_all", "gt_all", norm_loose)
    req_strict = agg("pred_required", "gt_required", norm)

    lat = sorted(r["latency_ms"] for r in oks)
    def q(p):
        if not lat:
            return 0.0
        i = min(len(lat) - 1, int(round((len(lat) - 1) * p)))
        return lat[i]

    # ---- 分组指标（规范一致性 / 业务一致性分开报）----
    groups = defaultdict(list)
    for r in oks:
        groups[r.get("group", "unknown")].append(r)
    by_group = {}
    for g, items in sorted(groups.items()):
        ag = sum(1 for r in items if r["pred_conclusion"] == r["gt_conclusion"])
        gl = sorted(r["latency_ms"] for r in items)
        by_group[g] = {
            "label": GROUP_LABEL.get(g, g),
            "n": len(items),
            "agreement": round(ag / len(items), 4) if items else None,
            "agreement_n": f"{ag}/{len(items)}",
            "skill_required_strict": dict(zip(
                ("precision", "recall", "f1"),
                [_r(x) for x in agg("pred_required", "gt_required", norm, items)])),
            "avg_tokens": round(statistics.fmean([r["tokens"] for r in items]), 1) if items else 0,
            "latency_ms_p95": round(gl[min(len(gl) - 1, int(round((len(gl) - 1) * 0.95)))] if gl else 0, 1),
        }

    tokens = [r["tokens"] for r in oks]
    short_circuit = sum(1 for r in oks if r["llm_calls"] == 0)
    cache_hits = sum(1 for r in oks if r["cache_hit"])

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "eval_set": set_path.name,
        "eval_set_size": total,
        "with_llm": with_llm,
        "elapsed_seconds": round(elapsed_s, 1),
        "conclusion_agreement": round(agree / len(oks), 4) if oks else None,
        "conclusion_agreement_n": f"{agree}/{len(oks)}",
        "excluded_from_agreement": [r["id"] for r in excluded],
        "excluded_note": "边界兜底用例（测的是接口层职责，见 contract_set_v1.jsonl），不计入一致率",
        "confusion_gt_x_pred": {k: dict(v) for k, v in conf.items()},
        "by_group": by_group,
        "skill_all_strict": {"precision": _r(all_strict[0]), "recall": _r(all_strict[1]), "f1": _r(all_strict[2])},
        "skill_all_loose": {"precision": _r(all_loose[0]), "recall": _r(all_loose[1]), "f1": _r(all_loose[2])},
        "skill_required_strict": {"precision": _r(req_strict[0]), "recall": _r(req_strict[1]), "f1": _r(req_strict[2])},
        "avg_tokens": round(statistics.fmean(tokens), 1) if tokens else 0,
        "total_tokens": sum(tokens),
        "latency_ms_p50": round(q(0.50), 1),
        "latency_ms_p95": round(q(0.95), 1),
        "latency_ms_max": round(max(lat), 1) if lat else 0,
        "short_circuit_rate": round(short_circuit / len(oks), 4) if oks else None,
        "cache_hits": cache_hits,
        "error_count": len(errors),
        "errors": [{"id": r["id"], "error": r["error"]} for r in errors][:20],
    }
    return report, results


def _r(x):
    return None if x is None else round(x, 4)


def print_report(rep, results):
    print("=" * 72)
    print("简聘 · 评测报告")
    print("=" * 72)
    print(f"评测集      : {rep['eval_set']}（{rep['eval_set_size']} 条）")
    print(f"模式        : {'真实调 LLM' if rep['with_llm'] else '关 LLM（仅规则链路）'}")
    print(f"耗时        : {rep['elapsed_seconds']} 秒")
    print("-" * 72)
    print("【结论一致率】")
    print(f"  一致率    : {pct(rep['conclusion_agreement'])}  ({rep['conclusion_agreement_n']})")
    if rep.get("excluded_from_agreement"):
        print(f"  已剔除    : {rep['excluded_from_agreement']} ← {rep['excluded_note']}")
    print("  混淆矩阵 (行=期望, 列=实际):")
    for gt in ("推荐", "待定", "不推荐"):
        row = rep["confusion_gt_x_pred"].get(gt, {})
        if row:
            print(f"    {gt:<4} → " + "  ".join(f"{k}:{v}" for k, v in sorted(row.items())))
    print("-" * 72)
    print("【分组指标】两类口径分开报，不要混看")
    for g, info in rep.get("by_group", {}).items():
        sk = info["skill_required_strict"]
        print(f"  {info['label']}")
        print(f"    样本 {info['n']} 条 | 结论一致率 {pct(info['agreement'])} ({info['agreement_n']})"
              f" | 必须技能 P={pct(sk['precision'])} R={pct(sk['recall'])}"
              f" | P95={info['latency_ms_p95']}ms")
    print("-" * 72)
    print("【技能抽取】")
    s = rep["skill_all_strict"]
    print(f"  全部技能 严格口径  P={pct(s['precision'])}  R={pct(s['recall'])}  F1={pct(s['f1'])}")
    s = rep["skill_all_loose"]
    print(f"  全部技能 宽松口径  P={pct(s['precision'])}  R={pct(s['recall'])}  F1={pct(s['f1'])}")
    s = rep["skill_required_strict"]
    print(f"  必须技能 严格口径  P={pct(s['precision'])}  R={pct(s['recall'])}  F1={pct(s['f1'])}")
    print("-" * 72)
    print("【成本与性能】")
    print(f"  平均 token : {rep['avg_tokens']}（总 {rep['total_tokens']}）")
    print(f"  延迟       : P50={rep['latency_ms_p50']}ms  P95={rep['latency_ms_p95']}ms  Max={rep['latency_ms_max']}ms")
    if rep["with_llm"]:
        print(f"  低分短路率 : {pct(rep['short_circuit_rate'])}（llm_calls==0 占比）")
    else:
        # 修复 llm_calls 计数 bug 后：关 LLM 模式下每次调用都不会产生 LLM 调用，
        # 该指标恒为 100%，没有信息量 —— 与其报一个恒真的数字，不如标注为不适用。
        print("  低分短路率 : n/a（关 LLM 模式下所有调用均为 0 次，该指标无意义；请用 --with-llm）")
    print("-" * 72)
    print("【健康度】")
    print(f"  异常数     : {rep['error_count']}")
    print(f"  缓存命中数 : {rep['cache_hits']}（应为 0，验证关缓存生效）")
    for e in rep["errors"][:5]:
        print(f"    ! {e['id']}: {e['error'][:80]}")

    # ---- 不一致用例（Top 12，按"期望推荐却判不推荐"等危险程度排序）----
    bad = [r for r in results if r["ok"] and r["pred_conclusion"] != r["gt_conclusion"]]
    danger = {"推荐": 0, "待定": 1, "不推荐": 2}
    bad.sort(key=lambda r: abs(danger.get(r["gt_conclusion"], 1) - danger.get(r["pred_conclusion"], 1)), reverse=True)
    print("-" * 72)
    print(f"【结论不一致用例】共 {len(bad)} 条，展示前 12 条：")
    for r in bad[:12]:
        flag = "★需复核" if r["needs_human_review"] else ""
        print(f"  {r['id']} [{r['source']}] 期望={r['gt_conclusion']} 实际={r['pred_conclusion']} "
              f"分数={r['match_score']} {flag}")
        print(f"      缺={r['gt_required'][:4]} | 判出={r['pred_all'][:6]}")
    print("=" * 72)


async def main_async(args):
    set_path = Path(args.set) if args.set else DEFAULT_SET
    cases = load_set(set_path)
    if args.filter_source:
        cases = [c for c in cases if c["source"] == args.filter_source]
    if args.limit:
        cases = cases[: args.limit]

    # ---- 强制关缓存 ----
    agent._analyze_cache.clear()
    agent._result_cache.clear()

    # ---- 禁止评测数据写业务库 / 写 Trace 表 ----
    database.save_history = lambda *a, **kw: None
    import app.trace as _trace_mod
    _trace_mod.set_enabled(False)

    if not args.with_llm:
        config.DEEPSEEK_API_KEY = ""      # 两个 LLM 节点走降级分支

    print(f"开始跑批：{len(cases)} 条 | 模式={'with-llm' if args.with_llm else 'no-llm'} | 关缓存=True | 写业务库=False")
    t0 = time.perf_counter()
    results = []
    for i, case in enumerate(cases, 1):
        results.append(await run_one(case, args.with_llm))
        if i % 25 == 0 or i == len(cases):
            print(f"  ... {i}/{len(cases)}")
    elapsed = time.perf_counter() - t0

    rep, _ = summarize(results, set_path, args.with_llm, elapsed)
    print_report(rep, results)

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = BACKEND / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"report": rep, "cases": results}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"已保存: {out}")
    return rep


def main():
    ap = argparse.ArgumentParser(description="简聘评测跑批")
    ap.add_argument("--set", default="", help="评测集路径（默认 eval/eval_set_v1.jsonl）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    ap.add_argument("--with-llm", action="store_true", help="真实调用 LLM（慢且有费用）")
    ap.add_argument("--out", default="", help="把完整报告+逐条结果存成 JSON")
    ap.add_argument("--filter-source", default="", help="只跑某个 source（history/constructed/...）")
    args = ap.parse_args()

    import asyncio
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
