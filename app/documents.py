from __future__ import annotations

import re
from pathlib import Path

ALLOWED_SUFFIXES = {".pdf", ".doc", ".docx"}
_STEM = re.compile(r"[^\w\u4e00-\u9fff.-]+", re.UNICODE)


class DocumentError(Exception):
    pass


def safe_stem(name: str) -> str:
    stem = _STEM.sub("_", Path(name).stem).strip("._")
    return stem[:80] or "document"


def validate_document(path: Path) -> None:
    """只核对扩展名和文件头，不转换、不拆页、不读正文。"""
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentError("只支持 PDF、DOC 和 DOCX")
    head = path.read_bytes()[:8]
    if not head:
        raise DocumentError("文件是空的")
    if suffix == ".pdf" and not head.startswith(b"%PDF"):
        raise DocumentError("扩展名是 PDF，但内容不是 PDF")
    if suffix == ".docx" and not head.startswith(b"PK"):
        raise DocumentError("这个 DOCX 无法读取")
    if suffix == ".doc" and not head.startswith(b"\xd0\xcf\x11\xe0"):
        raise DocumentError("这个 DOC 无法读取")
