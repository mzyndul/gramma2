import hashlib
import threading
import time
from collections import OrderedDict

PROMPT_VERSION = "2"
MAX_CACHE_SIZE = 1000
CACHE_TTL_SECONDS = 3600


class ImproveCache:
    def __init__(self, max_size: int = MAX_CACHE_SIZE, ttl: int = CACHE_TTL_SECONDS):
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size
        self._ttl = ttl

    def _make_key(self, text: str, backend: str, model: str) -> str:
        raw = f"{backend}:{model}:{PROMPT_VERSION}:{text}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, text: str, backend: str, model: str) -> str | None:
        key = self._make_key(text, backend, model)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.time() - entry["created_at"] > self._ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return entry["suggestion"]

    def put(self, text: str, backend: str, model: str, suggestion: str) -> None:
        key = self._make_key(text, backend, model)
        with self._lock:
            self._cache[key] = {
                "suggestion": suggestion,
                "created_at": time.time(),
            }
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
