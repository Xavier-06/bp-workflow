from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from search.config import CACHE_DIR


class FileCache:
    def __init__(self, namespace: str):
        self.base = CACHE_DIR / namespace
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
        return self.base / f'{digest}.json'

    def get(self, key: str, ttl_seconds: int | None = None):
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            return None
        ts = data.get('_cached_at', 0)
        if ttl_seconds is not None and time.time() - ts > ttl_seconds:
            return None
        return data.get('value')

    def set(self, key: str, value) -> None:
        payload = {'_cached_at': time.time(), 'value': value}
        self._path(key).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
