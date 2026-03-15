import logging
import time
from concurrent.futures import ThreadPoolExecutor

from .backends import get_backend, model_for_backend
from .cache import ImproveCache

log = logging.getLogger("gramma2")

_cache = ImproveCache()


def clear_cache() -> None:
    _cache.clear()


MIN_TEXT_LENGTH = 3  # skip LLM for text shorter than this


def improve_single(text: str, backend: str) -> str:
    stripped = text.strip()
    if len(stripped) < MIN_TEXT_LENGTH:
        log.info("SKIP SHORT [%s] %r — returning as-is", backend, stripped)
        return text

    model = model_for_backend(backend)
    preview = text[:60].replace("\n", " ")

    cached = _cache.get(text, backend, model)
    if cached is not None:
        log.info("CACHE HIT  [%s] %r", backend, preview)
        return cached

    log.info("CACHE MISS [%s] %r — calling backend...", backend, preview)
    start = time.monotonic()
    fn = get_backend(backend)
    suggestion = fn(text)
    elapsed = time.monotonic() - start
    log.info("GENERATED  [%s] %.1fs %r", backend, elapsed, preview)

    _cache.put(text, backend, model, suggestion)
    return suggestion


def improve_batch(sentences: list[str], backend: str) -> list[dict]:
    max_workers = min(3, len(sentences))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(improve_single, s, backend)
            for s in sentences
        ]
        return [
            {"original": sentences[i], "suggestion": futures[i].result()}
            for i in range(len(sentences))
        ]
