from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

_TOKEN = re.compile(r"^[a-f0-9]{32}$")


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self) -> tuple[str, Path]:
        token = uuid.uuid4().hex
        path = self.root / token
        path.mkdir()
        return token, path

    def path_for(self, token: str) -> Path:
        if not _TOKEN.fullmatch(token):
            raise KeyError(token)
        path = self.root / token
        if not path.is_dir():
            raise KeyError(token)
        return path

    def write_meta(self, path: Path, meta: dict) -> None:
        (path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def read_meta(self, path: Path) -> dict:
        return json.loads((path / "meta.json").read_text(encoding="utf-8"))

    def delete(self, token: str) -> None:
        try:
            path = self.path_for(token)
        except KeyError:
            return
        shutil.rmtree(path, ignore_errors=True)

    def purge(self, max_age: float) -> None:
        if not self.root.exists():
            return
        now = time.time()
        for child in self.root.iterdir():
            try:
                if child.is_dir() and now - child.stat().st_mtime > max_age:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue
