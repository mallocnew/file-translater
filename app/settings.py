from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_UPLOAD_BYTES = 150 * 1024 * 1024
TEMP_FILE_MAX_AGE = 12 * 60 * 60


def configured_api_key() -> str:
    return os.environ.get("DASHSCOPE_API_KEY", "").strip()


def configured_base_url() -> str:
    return os.environ.get("DASHSCOPE_BASE_URL", "").strip() or DEFAULT_BASE_URL


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
