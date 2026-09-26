from __future__ import annotations

from common.cache.memory import MemoryCache
from common.cache.protocol import CacheBackend
from common.cache.redis import RedisCache
from config import ENVIRONMENT, ActiveConfig

_backend: CacheBackend | None = None


def get_cache() -> CacheBackend:
    """Process-wide cache backend. Redis when configured, memory otherwise."""

    global _backend
    if _backend is None:
        _backend = build_cache()
    return _backend


def build_cache(url: str | None = None) -> CacheBackend:
    redis_url = url if url is not None else ActiveConfig.REDIS_URL
    if redis_url and not ENVIRONMENT.is_test:
        return RedisCache(redis_url, prefix=ActiveConfig.CACHE_KEY_PREFIX)
    return MemoryCache()


def set_cache(backend: CacheBackend | None) -> None:
    """Tests swap in a fresh MemoryCache; pass None to rebuild the default."""

    global _backend
    _backend = backend
