"""简历文件提取：支持 PDF / DOCX（纯本地处理，零 LLM）。"""
import fitz  # PyMuPDF
from docx import Document
from fastapi import HTTPException

# 文件大小上限 5MB
MAX_FILE_SIZE = 5 * 1024 * 1024


def extract_pdf(content: bytes) -> str:
    doc = fitz.open(stream=content, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text.strip()


def extract_docx(content: bytes) -> str:
    from io import BytesIO

    doc = Document(BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    # 也尝试表格文本
    table_text = []
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    table_text.append(cell.text.strip())
    return "\n".join(paragraphs + table_text).strip()


def extract_resume(filename: str, content: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        return extract_pdf(content)
    elif filename.lower().endswith(".docx"):
        return extract_docx(content)
    else:
        raise HTTPException(status_code=400, detail="仅支持 PDF 或 DOCX 文件")
