from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx2

from app.catalog import is_layout_model, language_code, layout_language_error
from app.documents import DocumentError, safe_stem
from app.translate import (
    LiveCall,
    TranslateOptions,
    TranslationCancelled,
    _check_cancel,
    build_http_client,
    clean_base_url,
    resolve_api_key,
)

logger = logging.getLogger(__name__)

LAYOUT_MAX_BYTES = 100 * 1024 * 1024
_POLL_SECONDS = 5
_POLL_DEADLINE = 20 * 60
_GLOSSARY_LINE = re.compile(r"\s*[=：:]\s*")
_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def run_layout_translation(
    file_path: Path,
    filename: str,
    options: TranslateOptions,
    emit,
    cancel: threading.Event,
    live: LiveCall,
) -> None:
    if not is_layout_model(options.model):
        raise ValueError("这个模型不能保留排版输出文件")
    suffix = file_path.suffix.lower()
    if suffix == ".doc":
        raise DocumentError("保留排版不支持旧版 DOC，请另存为 DOCX 后再试")
    if suffix not in _MIME:
        raise DocumentError("保留排版只支持 PDF 和 DOCX")
    size = file_path.stat().st_size
    if size > LAYOUT_MAX_BYTES:
        raise DocumentError("保留排版单文件不能超过 100 MB")
    pair_error = layout_language_error(options.source_lang, options.target_lang)
    if pair_error:
        raise ValueError(pair_error)
    target = language_code(options.target_lang)
    if not target:
        raise ValueError("请填写目标语言")
    source = language_code(options.source_lang)
    api_key = resolve_api_key()
    base_url = clean_base_url()
    client = build_http_client(base_url)
    live.client = client
    try:
        emit({"type": "status", "message": "正在上传原文件"})
        file_url = _upload_temp_file(client, api_key, base_url, file_path, suffix)
        _check_cancel(cancel)
        emit({"type": "status", "message": "正在提交保留排版翻译"})
        task_id = _create_task(client, api_key, base_url, file_url, source, target, options)
        emit({"type": "status", "message": "模型正在按原格式翻译"})
        data, usage = _wait_task(client, api_key, base_url, task_id, cancel, emit)
        translated_url = str((data or {}).get("TranslatedFileUrl") or "").strip()
        if not translated_url:
            raise RuntimeError("模型没有返回译后文件")
        emit({"type": "status", "message": "正在下载译后文件"})
        dest_name = f"translated{suffix}"
        dest = file_path.parent / dest_name
        _download_file(client, translated_url, dest, cancel)
        download_name = f"{safe_stem(filename)}-{options.target_lang}{suffix}"
        _write_result_meta(file_path.parent, dest_name, download_name)
        emit(
            {
                "type": "done",
                "mode": "layout",
                "kind": suffix.lstrip("."),
                "filename": download_name,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            }
        )
    finally:
        live.close()


def parse_glossary(text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = _GLOSSARY_LINE.split(line, maxsplit=1)
        src = parts[0].strip()
        tgt = parts[1].strip() if len(parts) > 1 else ""
        if not src:
            continue
        items.append({"src": src[:200], "tgt": tgt[:200]})
        if len(items) >= 100:
            break
    return items


def dashscope_origin(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def uploads_url(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    if "intl" in host or "ap-southeast" in host:
        return "https://dashscope-intl.aliyuncs.com/api/v1/uploads"
    return "https://dashscope.aliyuncs.com/api/v1/uploads"


def generation_url(base_url: str) -> str:
    return dashscope_origin(base_url) + "/api/v1/services/aigc/multimodal-generation/generation"


def tasks_url(base_url: str, task_id: str) -> str:
    return dashscope_origin(base_url) + "/api/v1/tasks/" + task_id


def _upload_temp_file(client: httpx2.Client, api_key: str, base_url: str, path: Path, suffix: str) -> str:
    policy = _get_policy(client, api_key, base_url)
    upload_name = f"document{suffix}"
    key = f"{policy['upload_dir']}/{upload_name}"
    with path.open("rb") as handle:
        files = [
            ("OSSAccessKeyId", (None, str(policy["oss_access_key_id"]))),
            ("Signature", (None, str(policy["signature"]))),
            ("policy", (None, str(policy["policy"]))),
            ("x-oss-object-acl", (None, str(policy.get("x_oss_object_acl") or "private"))),
            ("x-oss-forbid-overwrite", (None, str(policy.get("x_oss_forbid_overwrite") or "true"))),
            ("key", (None, key)),
            ("success_action_status", (None, "200")),
            ("file", (upload_name, handle, _MIME[suffix])),
        ]
        response = client.post(str(policy["upload_host"]), files=files, timeout=300.0)
        if response.status_code not in {200, 204}:
            raise RuntimeError(_http_error("上传原文件失败", response))
    return f"oss://{key}"


def _get_policy(client: httpx2.Client, api_key: str, base_url: str) -> dict:
    response = client.get(
        uploads_url(base_url),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        params={"action": "getPolicy", "model": "qwen-mt-uni"},
        timeout=30.0,
    )
    if response.status_code != 200:
        raise RuntimeError(_http_error("获取上传凭证失败", response))
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("upload_host"):
        raise RuntimeError("模型接口没有返回上传凭证")
    return data


def _create_task(
    client: httpx2.Client,
    api_key: str,
    base_url: str,
    file_url: str,
    source: str | None,
    target: str,
    options: TranslateOptions,
) -> str:
    body_input: dict = {
        "fileUrl": file_url,
        "target_lang": target,
    }
    if source:
        body_input["source_lang"] = source
    ext: dict = {}
    glossary = parse_glossary(options.glossary)
    if glossary:
        ext["glossary"] = glossary
    hint = _domain_hint(options.instructions)
    if hint:
        ext["domainHint"] = hint
    if ext:
        body_input["ext"] = ext
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
        "X-DashScope-OssResourceResolve": "enable",
    }
    response = client.post(
        generation_url(base_url),
        headers=headers,
        json={"model": "qwen-mt-uni", "input": body_input},
        timeout=60.0,
    )
    payload = _json_body(response)
    if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("code") and not payload.get("output")):
        raise RuntimeError(_api_error("提交翻译任务失败", response, payload))
    output = payload.get("output") if isinstance(payload, dict) else None
    task_id = str((output or {}).get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError("模型接口没有返回任务编号")
    return task_id


def _wait_task(
    client: httpx2.Client,
    api_key: str,
    base_url: str,
    task_id: str,
    cancel: threading.Event,
    emit,
) -> tuple[dict, dict[str, int]]:
    deadline = time.monotonic() + _POLL_DEADLINE
    last_status = ""
    while True:
        _check_cancel(cancel)
        if time.monotonic() > deadline:
            raise RuntimeError("保留排版翻译超时，请稍后重试")
        response = client.get(
            tasks_url(base_url, task_id),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        payload = _json_body(response)
        if response.status_code >= 400:
            raise RuntimeError(_api_error("查询翻译任务失败", response, payload))
        output = payload.get("output") if isinstance(payload, dict) else None
        if not isinstance(output, dict):
            raise RuntimeError("查询翻译任务时没有返回结果")
        status = str(output.get("task_status") or "")
        if status != last_status:
            last_status = status
            if status == "PENDING":
                emit({"type": "status", "message": "翻译任务排队中"})
            elif status == "RUNNING":
                emit({"type": "status", "message": "模型正在按原格式翻译"})
        if status in {"FAILED", "UNKNOWN"}:
            raise RuntimeError(str(output.get("Message") or "保留排版翻译失败"))
        if status == "SUCCEEDED":
            if output.get("Success") is False:
                raise RuntimeError(str(output.get("Message") or "保留排版翻译失败"))
            data = output.get("Data")
            if not isinstance(data, dict):
                raise RuntimeError("模型没有返回译后文件")
            usage = _usage(payload.get("usage") if isinstance(payload, dict) else None)
            return data, usage
        time.sleep(_POLL_SECONDS)


def _download_file(client: httpx2.Client, url: str, dest: Path, cancel: threading.Event) -> None:
    _check_cancel(cancel)
    with client.stream("GET", url, follow_redirects=True, timeout=300.0) as response:
        if response.status_code >= 400:
            raise RuntimeError(f"下载译后文件失败：HTTP {response.status_code}")
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes():
                _check_cancel(cancel)
                handle.write(chunk)
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError("译后文件是空的")


def _write_result_meta(folder: Path, dest_name: str, download_name: str) -> None:
    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    meta["result"] = {"file": dest_name, "filename": download_name}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _domain_hint(text: str) -> str | None:
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    letters = sum(1 for char in cleaned if char.isascii() and char.isalpha())
    if letters < max(8, int(len(cleaned) * 0.45)):
        return None
    return " ".join(cleaned.split()[:200])


def _usage(raw) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {"input_tokens": 0, "output_tokens": 0}
    return {
        "input_tokens": int(raw.get("input_tokens") or 0),
        "output_tokens": int(raw.get("output_tokens") or 0),
    }


def _json_body(response: httpx2.Response):
    try:
        return response.json()
    except Exception:
        return {}


def _http_error(prefix: str, response: httpx2.Response) -> str:
    return _api_error(prefix, response, _json_body(response))


def _api_error(prefix: str, response: httpx2.Response, payload) -> str:
    detail = ""
    if isinstance(payload, dict):
        detail = str(payload.get("message") or payload.get("Message") or "")
        if not detail and isinstance(payload.get("error"), dict):
            detail = str(payload["error"].get("message") or "")
    if not detail:
        text = (response.text or "").strip()
        detail = text[:300]
    extra = f"：{detail}" if detail else ""
    return f"{prefix}（HTTP {response.status_code}{extra}）"
