from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx2
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.documents import safe_stem
from app.settings import configured_api_key, configured_base_url
from app.textutil import ThinkFilter, strip_wrapping_fence

logger = logging.getLogger(__name__)

_MODEL_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class TranslationCancelled(Exception):
    pass


@dataclass
class TranslateOptions:
    model: str
    target_lang: str
    source_lang: str
    glossary: str
    instructions: str


class LiveCall:
    def __init__(self) -> None:
        self.client: OpenAI | None = None
        self.stream = None
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            stream, self.stream = self.stream, None
            client, self.client = self.client, None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                logger.debug("closing stream failed", exc_info=True)
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.debug("closing client failed", exc_info=True)


def clean_base_url() -> str:
    candidate = configured_base_url().strip().rstrip("/")
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"} or not host:
        raise ValueError("接口地址需要是完整的 http(s) URL")
    if parsed.scheme == "http" and host not in _LOCAL_HOSTS:
        raise ValueError("除本机地址外，接口需要使用 https")
    if not parsed.path or parsed.path == "/":
        raise ValueError("接口地址需要带路径，例如 /compatible-mode/v1")
    return candidate


def resolve_api_key() -> str:
    key = configured_api_key()
    if not key:
        raise ValueError("请在服务端 .env 中配置 DASHSCOPE_API_KEY")
    if len(key) > 300 or any(char.isspace() for char in key):
        raise ValueError("API Key 格式不对")
    return key


def normalize_options(options: TranslateOptions) -> TranslateOptions:
    model = options.model.strip()
    if not _MODEL_ID.fullmatch(model):
        raise ValueError("模型名称只能包含字母、数字、点、下划线和连字符")
    target = " ".join(options.target_lang.split())
    source = " ".join(options.source_lang.split()) or "自动检测"
    if not target or len(target) > 40:
        raise ValueError("请填写目标语言")
    if len(source) > 40:
        raise ValueError("原文语言过长")
    glossary = options.glossary.strip()
    instructions = options.instructions.strip()
    if len(glossary) > 4000 or len(instructions) > 2000:
        raise ValueError("术语表或补充要求太长")
    return TranslateOptions(
        model=model,
        target_lang=target,
        source_lang=source,
        glossary=glossary,
        instructions=instructions,
    )


def run_translation(
    file_path: Path,
    filename: str,
    options: TranslateOptions,
    emit,
    cancel: threading.Event,
    live: LiveCall,
) -> None:
    options = normalize_options(options)
    api_key = resolve_api_key()
    base_url = clean_base_url()
    logger.info("translate model=%s file=%s", options.model, file_path.suffix.lower())
    _check_cancel(cancel)
    client = make_client(api_key, base_url)
    live.client = client
    file_id = None
    try:
        emit({"type": "status", "message": "正在把原文件交给模型"})
        file_id = _upload_original(client, file_path, filename)
        _wait_until_ready(client, file_id, cancel, emit)
        emit({"type": "status", "message": "模型正在翻译"})
        usage = {"input_tokens": 0, "output_tokens": 0}
        piece = _stream_translation(client, live, options, file_id, usage, emit, cancel)
        text = strip_wrapping_fence(piece).strip()
        if not text:
            raise RuntimeError("模型没有返回译文")
        emit(
            {
                "type": "done",
                "text": text,
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "chars": len(text),
            }
        )
    finally:
        if file_id is not None:
            try:
                client.files.delete(file_id)
            except Exception:
                logger.warning("delete remote file failed")
        live.close()


def build_prompt(options: TranslateOptions) -> str:
    source = ""
    if options.source_lang and options.source_lang != "自动检测":
        source = f"原文语言是{options.source_lang}。"
    parts = [
        f"请阅读已提供的原文件，把其中全部内容翻译成{options.target_lang}。{source}",
        "\n".join(
            [
                "要求：",
                "1. 按阅读顺序翻译正文、标题、表格、列表、图注、脚注，以及页眉页脚里的实质内容。",
                "2. 用 Markdown 输出。标题层级与原文对应，表格用 Markdown 表格，公式用 LaTeX。",
                "3. 保留数字、单位、代码、网址和邮箱。专有名词可以保留原文。",
                "4. 不要总结，不要评论，不要省略，不要输出思考过程。看不清的地方写成〔无法辨认〕。",
                "5. 只输出译文本身。",
            ]
        ),
    ]
    if options.glossary:
        parts.append("术语表，必须按这个译：\n" + options.glossary)
    if options.instructions:
        parts.append("补充要求：\n" + options.instructions)
    return "\n\n".join(parts)


def make_client(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=build_http_client(base_url),
        timeout=httpx2.Timeout(900.0, connect=30.0),
        max_retries=0,
    )


def build_http_client(base_url: str) -> httpx2.Client:
    # SDK 自带的 httpx2 不认识 ALL_PROXY=socks://，这里只沿用 http/https 代理。
    host = (urlparse(base_url).hostname or "").lower()
    proxy = None if host in _LOCAL_HOSTS else _http_proxy()
    kwargs: dict = {
        "timeout": httpx2.Timeout(900.0, connect=30.0),
        "follow_redirects": True,
        "trust_env": False,
    }
    if proxy:
        kwargs["proxy"] = proxy
    return httpx2.Client(**kwargs)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, APITimeoutError):
        return "模型长时间没有返回内容，请稍后重试。"
    if isinstance(exc, APIStatusError):
        message = _error_message(exc) or str(exc)
        return f"模型接口返回 {exc.status_code}：{message}"
    if isinstance(exc, APIConnectionError):
        return "连接模型接口失败。请检查接口地址、网络和密钥所属地域是否一致。"
    text = str(exc).strip()
    return text[:500] or "翻译失败"


def _upload_original(client: OpenAI, path: Path, filename: str) -> str:
    upload_name = _safe_upload_name(filename, path.suffix.lower())
    with path.open("rb") as handle:
        uploaded = client.files.create(file=(upload_name, handle), purpose="file-extract")
    file_id = getattr(uploaded, "id", None)
    if not file_id:
        raise RuntimeError("模型接口没有返回文件编号")
    return str(file_id)


def _wait_until_ready(client: OpenAI, file_id: str, cancel: threading.Event, emit) -> None:
    emit({"type": "status", "message": "模型正在解析原文件"})
    deadline = time.monotonic() + 300
    while True:
        _check_cancel(cancel)
        info = client.files.retrieve(file_id)
        status = str(getattr(info, "status", "") or "")
        if status == "processed":
            return
        if status in {"error", "failed"}:
            detail = getattr(info, "status_details", None)
            extra = f"：{detail}" if detail else ""
            raise RuntimeError(f"模型没能解析这个文件{extra}")
        if time.monotonic() > deadline:
            raise RuntimeError("文件解析超时，请稍后重试")
        time.sleep(2)


def _file_messages(file_id: str, prompt: str) -> list[dict]:
    return [
        {"role": "system", "content": "你是严谨的文档翻译员。只翻译已提供的文件，不解释。"},
        {"role": "system", "content": f"fileid://{file_id}"},
        {"role": "user", "content": prompt},
    ]


def _safe_upload_name(filename: str, suffix: str) -> str:
    return f"{safe_stem(filename)}{suffix}"


def _stream_translation(client, live, options, file_id: str, usage, emit, cancel) -> str:
    messages = _file_messages(file_id, build_prompt(options))
    kwargs = {
        "model": options.model,
        "messages": messages,
        "temperature": 0.2,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if "qwen3" in options.model:
        kwargs["extra_body"] = {"enable_thinking": False}
    stream = client.chat.completions.create(**kwargs)
    live.stream = stream
    visible = ThinkFilter()
    collected: list[str] = []
    try:
        for chunk in stream:
            _check_cancel(cancel)
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage["input_tokens"] += int(getattr(chunk_usage, "prompt_tokens", 0) or 0)
                usage["output_tokens"] += int(getattr(chunk_usage, "completion_tokens", 0) or 0)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            piece = visible.push(_delta_text(delta))
            if not piece:
                continue
            collected.append(piece)
            emit({"type": "token", "text": piece})
        tail = visible.finish()
        if tail:
            collected.append(tail)
            emit({"type": "token", "text": tail})
        return "".join(collected)
    finally:
        live.stream = None
        try:
            stream.close()
        except Exception:
            logger.debug("stream close failed", exc_info=True)


def _delta_text(delta) -> str:
    content = getattr(delta, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for item in content:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, dict):
                pieces.append(str(item.get("text") or ""))
            else:
                pieces.append(str(getattr(item, "text", "") or ""))
        return "".join(pieces)
    return ""


def _error_message(exc: APIStatusError) -> str:
    body = exc.body
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
        if body.get("message"):
            return str(body["message"])[:500]
    if isinstance(body, str) and body.strip():
        return body.strip()[:500]
    return ""


def _http_proxy() -> str | None:
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(name, "").strip()
        if value.startswith(("http://", "https://")):
            return value
    return None


def _check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise TranslationCancelled()
