from __future__ import annotations

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.catalog import LANGUAGES, MODELS
from app.docx_export import markdown_to_docx
from app.documents import ALLOWED_SUFFIXES, DocumentError, safe_stem, validate_document
from app.settings import (
    DATA_DIR,
    MAX_UPLOAD_BYTES,
    ROOT,
    TEMP_FILE_MAX_AGE,
    configured_api_key,
    configured_base_url,
    load_dotenv,
)
from app.store import Store
from app.translate import LiveCall, TranslateOptions, TranslationCancelled, friendly_error, run_translation

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STATIC = ROOT / "static"
store = Store(DATA_DIR / "prepared")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.purge(max_age=TEMP_FILE_MAX_AGE)
    task = asyncio.create_task(_purge_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="页译", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class TranslateRequest(BaseModel):
    model: str
    target_lang: str
    source_lang: str = "自动检测"
    glossary: str = ""
    instructions: str = ""


class ExportRequest(BaseModel):
    markdown: str = Field(max_length=2_000_000)
    filename: str = "translation.docx"


@app.exception_handler(DocumentError)
async def document_error(_request: Request, exc: DocumentError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/config")
def config() -> dict:
    return {
        "has_server_key": bool(configured_api_key()),
        "endpoint_host": urlparse(configured_base_url()).hostname or "",
        "models": [item.payload() for item in MODELS],
        "languages": list(LANGUAGES),
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }


@app.post("/api/prepare")
async def prepare(file: UploadFile = File(...)) -> dict:
    name = Path(file.filename or "document").name
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentError("只支持 PDF、DOC 和 DOCX")
    token, folder = store.create()
    source_path = folder / f"source{suffix}"
    try:
        size = await _save_upload(file, source_path)
        validate_document(source_path)
        meta = {
            "filename": name,
            "stem": safe_stem(name),
            "kind": suffix.lstrip("."),
            "size": size,
        }
        store.write_meta(folder, meta)
        folder.touch()
        return {"token": token, **meta}
    except Exception:
        store.delete(token)
        raise


@app.delete("/api/prepare/{token}")
def discard(token: str) -> dict:
    store.delete(token)
    return {"ok": True}


@app.post("/api/translate/{token}")
async def translate(token: str, body: TranslateRequest, request: Request) -> StreamingResponse:
    folder = _folder(token)
    meta = store.read_meta(folder)
    file_path = folder / f"source.{meta['kind']}"
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="找不到文档")
    folder.touch()
    options = TranslateOptions(
        model=body.model,
        target_lang=body.target_lang,
        source_lang=body.source_lang,
        glossary=body.glossary,
        instructions=body.instructions,
    )
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    cancel = threading.Event()
    live = LiveCall()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def work() -> None:
        try:
            run_translation(file_path, str(meta["filename"]), options, emit, cancel, live)
        except TranslationCancelled:
            emit({"type": "cancelled"})
        except (DocumentError, ValueError) as exc:
            emit({"type": "error", "message": str(exc)})
        except Exception as exc:
            logger.error("translation failed: %s", exc.__class__.__name__)
            emit({"type": "error", "message": friendly_error(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def events():
        task = asyncio.create_task(asyncio.to_thread(work))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        cancel.set()
                        break
                    yield ": ping\n\n"
                    continue
                if event is None:
                    break
                if await request.is_disconnected():
                    cancel.set()
                    break
                yield _sse(event)
                if event.get("type") in {"done", "error", "cancelled"}:
                    break
        finally:
            cancel.set()
            live.close()
            await task

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/export/docx")
def export_docx(body: ExportRequest) -> Response:
    filename = _download_name(body.filename)
    data = markdown_to_docx(body.markdown)
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": disposition},
    )


def _folder(token: str) -> Path:
    try:
        return store.path_for(token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文档不存在或已过期") from exc


async def _save_upload(file: UploadFile, dest: Path) -> int:
    size = 0
    try:
        with dest.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise DocumentError(f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                handle.write(chunk)
    finally:
        await file.close()
    if size == 0:
        raise DocumentError("文件是空的")
    return size


def _download_name(name: str) -> str:
    cleaned = Path(name).name.replace("\x00", "")
    if not cleaned.lower().endswith(".docx"):
        cleaned = f"{cleaned or 'translation'}.docx"
    return cleaned[:120]


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _purge_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        store.purge(max_age=TEMP_FILE_MAX_AGE)
