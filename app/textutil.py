from __future__ import annotations

_TAGS = (("<think>", "</think>"), ("<thinking>", "</thinking>"))


class ThinkFilter:
    """丢掉模型夹在正文里的思考片段，包括被拆到多次输出里的标签。"""

    def __init__(self) -> None:
        self._hold = ""
        self._closing: str | None = None

    def push(self, text: str) -> str:
        if not text:
            return ""
        self._hold += text
        pieces: list[str] = []
        while self._hold:
            if self._closing:
                index = self._hold.find(self._closing)
                if index == -1:
                    keep = len(self._closing) - 1
                    if len(self._hold) > keep:
                        self._hold = self._hold[-keep:]
                    break
                self._hold = self._hold[index + len(self._closing) :]
                self._closing = None
                continue
            found = self._find_open()
            if found is None:
                cut = self._partial_tail()
                emit = len(self._hold) - cut
                if emit > 0:
                    pieces.append(self._hold[:emit])
                    self._hold = self._hold[emit:]
                break
            start, opener, closer = found
            pieces.append(self._hold[:start])
            self._hold = self._hold[start + len(opener) :]
            self._closing = closer
        return "".join(pieces)

    def finish(self) -> str:
        if self._closing:
            self._hold = ""
            self._closing = None
            return ""
        text = self._hold
        self._hold = ""
        return text

    def _find_open(self) -> tuple[int, str, str] | None:
        found: tuple[int, str, str] | None = None
        for opener, closer in _TAGS:
            index = self._hold.find(opener)
            if index != -1 and (found is None or index < found[0]):
                found = (index, opener, closer)
        return found

    def _partial_tail(self) -> int:
        best = 0
        for opener, _closer in _TAGS:
            limit = min(len(self._hold), len(opener) - 1)
            for size in range(limit, 0, -1):
                if opener.startswith(self._hold[-size:]):
                    best = max(best, size)
                    break
        return best


def strip_wrapping_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.split("\n")
    if len(lines) < 2 or not lines[-1].strip().startswith("```"):
        return text
    body = "\n".join(lines[1:-1])
    return body.strip() + ("\n" if text.endswith("\n") else "")
