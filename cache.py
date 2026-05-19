"""Disk cache for API responses. Adapted from
D:\\uspto\\backup\\translate_patent.py:36-63 (TranslationCache).

Keys are MD5(sha256(pdf_bytes) + ":" + PROMPT_VERSION + ":" + tag).
Values are arbitrary JSON-serializable payloads (Pass 1 returns a dict;
Pass 2 returns an SVG string).

Survives across runs so re-invocations after the API's 5-minute
ephemeral cache TTL expires still cost nothing.
"""

import hashlib
import json
import os
import tempfile
from typing import Any, Optional


class ResponseCache:
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.cache_file):
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except (json.JSONDecodeError, IOError):
            self.data = {}

    def save(self) -> None:
        """Atomic write: temp file in the same dir, then os.replace."""
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        dir_ = os.path.dirname(self.cache_file)
        fd, tmp_path = tempfile.mkstemp(prefix=".cache_", suffix=".json", dir=dir_)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp_path, self.cache_file)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    @staticmethod
    def make_key(pdf_sha256: str, prompt_version: str, tag: str) -> str:
        raw = f"{pdf_sha256}:{prompt_version}:{tag}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        return self.data.get(key)

    def put(self, key: str, value: Any) -> None:
        self.data[key] = value

    def has(self, key: str) -> bool:
        return key in self.data

    def drop(self, key: str) -> None:
        self.data.pop(key, None)
