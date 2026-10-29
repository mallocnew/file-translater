from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    hint: str

    def payload(self) -> dict:
        return asdict(self)


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "qwen-long",
        "Qwen-Long",
        "推荐。原文件直接交给模型，不在本地拆页或转换。请使用北京地域的密钥。",
    ),
    ModelSpec(
        "qwen-doc-turbo",
        "Qwen-Doc-Turbo",
        "原文件直接交给模型，能读 PDF、DOC 和 DOCX。请使用北京地域的密钥。",
    ),
)

LANGUAGES: tuple[str, ...] = (
    "简体中文",
    "繁体中文",
    "英语",
    "日语",
    "韩语",
    "法语",
    "德语",
    "西班牙语",
    "俄语",
    "葡萄牙语",
    "意大利语",
    "阿拉伯语",
    "越南语",
    "泰语",
    "印尼语",
    "荷兰语",
    "土耳其语",
    "波兰语",
)
