from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    hint: str
    mode: str = "text"

    def payload(self) -> dict:
        return asdict(self)


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "qwen-long",
        "Qwen-Long",
        "推荐。原文件直接交给模型，译文以 Markdown 显示，可再导出 Word 或 PDF。请使用北京地域的密钥。",
    ),
    ModelSpec(
        "qwen-doc-turbo",
        "Qwen-Doc-Turbo",
        "原文件直接交给模型，能读 PDF、DOC 和 DOCX。译文同样是 Markdown。请使用北京地域的密钥。",
    ),
    ModelSpec(
        "qwen-mt-uni",
        "Qwen-MT-Uni",
        "保留排版。交回与原文相同格式的 PDF 或 Word。不支持旧版 DOC。请使用北京地域的密钥。",
        "layout",
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

LANGUAGE_CODES: dict[str, str] = {
    "简体中文": "zh",
    "繁体中文": "zh-tw",
    "英语": "en",
    "日语": "ja",
    "韩语": "ko",
    "法语": "fr",
    "德语": "de",
    "西班牙语": "es",
    "俄语": "ru",
    "葡萄牙语": "pt",
    "意大利语": "it",
    "阿拉伯语": "ar",
    "越南语": "vi",
    "泰语": "th",
    "印尼语": "id",
    "荷兰语": "nl",
    "土耳其语": "tr",
    "波兰语": "pl",
}

# Qwen-MT-Uni 官方语向表。源语种自动检测时不做这项校验。
_MT_UNI_FROM_EN = {
    "ar", "az", "bn", "bs", "cs", "da", "de", "el", "es", "et", "fi", "fr", "he", "hi",
    "hu", "id", "it", "ja", "ko", "lt", "lv", "ms", "my", "ne", "nl", "no", "pl", "pt",
    "pt-pt", "ro", "ru", "si", "sk", "sl", "sr", "sv", "th", "tl", "tr", "uk", "ur",
    "vi", "zh", "zh-tw",
}
MT_UNI_TARGETS: dict[str, frozenset[str]] = {
    "zh": frozenset({"zh-tw", "en", "ja", "ko", "kk", "ms", "th"}),
    "zh-tw": frozenset({"zh", "en", "ja", "ko", "kk", "ms", "th"}),
    "en": frozenset(_MT_UNI_FROM_EN),
    "es": frozenset({
        "bg", "cs", "da", "de", "el", "en", "et", "fi", "fr", "hr", "hu", "it",
        "lt", "lv", "nl", "no", "pl", "pt", "pt-pt", "ro", "ru", "sk", "sv",
    }),
    "ar": frozenset({"en", "tr"}),
    "tr": frozenset({"ar", "cs", "de", "el", "en", "hu", "ro", "sk"}),
    "ro": frozenset({"en", "tr"}),
}
for _code in (
    "az", "bn", "cs", "de", "el", "fi", "fr", "he", "hi", "hu", "id", "it", "ja",
    "ko", "ms", "my", "ne", "nl", "pl", "pt", "ru", "si", "sv", "th", "tl", "uk",
    "ur", "vi", "bg", "bs", "da", "et", "hr", "lt", "lv", "no", "pt-pt", "sk", "sl", "sr",
):
    MT_UNI_TARGETS.setdefault(_code, frozenset({"en"}))


def is_layout_model(model: str) -> bool:
    return model.strip().lower() == "qwen-mt-uni"


def language_code(name: str) -> str | None:
    text = " ".join(name.split())
    if not text or text == "自动检测":
        return None
    if text in LANGUAGE_CODES:
        return LANGUAGE_CODES[text]
    lowered = text.lower().replace("_", "-")
    if lowered in LANGUAGE_CODES.values() or lowered in MT_UNI_TARGETS:
        return lowered
    return None


def layout_language_error(source_lang: str, target_lang: str) -> str | None:
    target = language_code(target_lang)
    if not target:
        return "Qwen-MT-Uni 需要明确的目标语言"
    source = language_code(source_lang)
    if source is None:
        return None
    allowed = MT_UNI_TARGETS.get(source)
    if allowed is None:
        return f"Qwen-MT-Uni 暂不支持从{source_lang}翻译"
    if target not in allowed:
        return f"Qwen-MT-Uni 不支持从{source_lang}译成{target_lang}"
    return None

