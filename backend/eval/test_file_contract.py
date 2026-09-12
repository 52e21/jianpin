# -*- coding: utf-8 -*-
"""
第 15 步验收：前后端文件类型契约必须一致

做法（跨语言静态 + 后端行为双向核对）：
  A. 从后端 upload.py 读出实际支持的后缀集合（用行为验证，不信注释）
  B. 从 fontend/src/components/file-upload.tsx 读出 accept 与 validTypes
  C. 断言：前端放行的每一种类型，后端都能处理；后端不支持的不得出现在前端
  D. 对 .doc 给出可操作提示（不是笼统的"仅支持 PDF 或 DOCX"）

用法：python eval/test_file_contract.py
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "frontend"
sys.path.insert(0, str(BACKEND))

from fastapi import HTTPException          # noqa: E402
from app.upload import extract_resume      # noqa: E402

UPLOAD_TSX = FRONTEND / "src" / "components" / "file-upload.tsx"


def backend_supported():
    """用行为验证后端支持哪些后缀（不读注释）。"""
    # 构造一个最小合法 docx（zip 结构）与空 pdf；这里只关心"是否因后缀被拒"
    supported, rejected = set(), {}
    for name in ("a.pdf", "b.docx", "c.doc", "d.txt", "e.DOCX", "f.PDF"):
        try:
            extract_resume(name, b"")     # 空内容会在解析阶段报错，但后缀已通过
            supported.add(name.split(".")[-1].lower())
        except HTTPException as e:
            detail = e.detail
            if "仅支持" in detail or "不支持" in detail:
                rejected[name.split(".")[-1].lower()] = detail
            else:
                supported.add(name.split(".")[-1].lower())
        except Exception:
            supported.add(name.split(".")[-1].lower())   # 后缀通过，内容解析失败
    return supported, rejected


def frontend_accepts():
    src = UPLOAD_TSX.read_text(encoding="utf-8")
    acc = re.search(r'accept\s*=\s*"([^"]+)"', src)
    accept_exts = {e.strip().lstrip(".").lower() for e in acc.group(1).split(",")} if acc else set()
    types_block = re.search(r"const validTypes = \[(.*?)\]", src, re.S)
    mimes = set(re.findall(r'"([^"]+)"', types_block.group(1))) if types_block else set()
    return accept_exts, mimes, src


def main():
    print("=== A. 后端实际支持的后缀（行为验证）===")
    supported, rejected = backend_supported()
    print(f"  支持: {sorted(supported)}")
    for ext, msg in sorted(rejected.items()):
        print(f"  拒绝 .{ext}: {msg}")
    ok_backend = supported == {"pdf", "docx"} and "doc" in rejected

    print("\n=== B. 前端放行的类型 ===")
    exts, mimes, src = frontend_accepts()
    print(f"  accept 后缀: {sorted(exts)}")
    print(f"  validTypes MIME: {sorted(mimes)}")

    print("\n=== C. 契约一致性 ===")
    a1 = exts == supported, f"accept 后缀 {sorted(exts)} == 后端支持 {sorted(supported)}"
    a2 = "application/msword" not in mimes, "validTypes 不再放行 application/msword（.doc）"
    a3 = "application/pdf" in mimes and any("wordprocessingml" in m for m in mimes), "validTypes 含 pdf 与 docx"
    a4 = "不支持旧版 .doc" in src, "前端对 .doc 给出可操作提示"
    a5 = "不支持旧版 .doc" in rejected.get("doc", ""), "后端对 .doc 给出可操作提示"
    for good, desc in (a1, a2, a3, a4, a5):
        print(f"  {'OK  ' if good else 'FAIL'} {desc}")
    ok_contract = all(x[0] for x in (a1, a2, a3, a4, a5))

    print("\n=== D. 其余文案一致性 ===")
    d1 = "PDF/DOCX" in (FRONTEND / "src" / "routes" / "match.tsx").read_text(encoding="utf-8")
    d2 = "支持 PDF、DOCX 格式" in src
    for good, desc in ((d1, "输入页占位文案已改为 PDF/DOCX"), (d2, "上传组件提示文案已改为 PDF、DOCX")):
        print(f"  {'OK  ' if good else 'FAIL'} {desc}")
    ok_text = d1 and d2

    ok = ok_backend and ok_contract and ok_text
    print("\n总结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
