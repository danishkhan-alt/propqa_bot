from __future__ import annotations

from typing import Any

from common.cache.factory import get_cache
from common.cache.protocol import MISSING
from common.identity import Caller
from config import ActiveConfig


class CallerScopedCache:
    """A cache bound to one caller, with kind + id built into every key.

    Registered user A and visitor B can both write ``chat:last`` and never
    see each other's values. The kind is not optional: constructing this
    without a caller is how one population would leak into the other.
    """

    def __init__(self, caller: Caller, backend=None) -> None:
        if caller is None or not caller.subject_id:
            raise ValueError(
                "UserCache needs a caller. Take it from request.state.caller "
                "-- an unscoped entry is a leak between visitors and users."
            )
        self.caller = caller
        self._cache = backend if backend is not None else get_cache()

    def get(self, key: str, default: Any = None) -> Any:
        value = self._cache.get(self.scoped_key(key), MISSING)
        return default if value is MISSING else value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """``ttl=None`` uses the backend default, not 'forever'."""

        timeout = ActiveConfig.CACHE_TTL_SECONDS if ttl is None else ttl
        self._cache.set(self.scoped_key(key), value, ttl=timeout)

    def get_or_set(self, key: str, factory, ttl: int | None = None) -> Any:
        value = self.get(key, MISSING)
        if value is not MISSING:
            return value
        computed = factory()
        self.set(key, computed, ttl)
        return computed

    def invalidate(self, key: str) -> None:
        self._cache.delete(self.scoped_key(key))

    def invalidate_category(self, category: str) -> None:
        self._increment_generation(self._caller_category_generation_key(category))

    def invalidate_all(self) -> None:
        self._increment_generation(self._caller_generation_key())

    def scoped_key(self, key: str) -> str:
        """``chat:last`` becomes ``chat:registered:<id>:g1.1:last``."""

        category, separator, rest = key.partition(":")
        caller_generation, category_generation = self._generations(category)
        stem = (
            f"{category}:{self.caller.identity_key}:"
            f"g{caller_generation}.{category_generation}"
        )
        return f"{stem}:{rest}" if separator else stem

    def _generations(self, category: str) -> tuple[int, int]:
        caller_key = self._caller_generation_key()
        category_key = self._caller_category_generation_key(category)
        found = self._cache.get_many([caller_key, category_key])
        return found.get(caller_key, 1), found.get(category_key, 1)

    def _caller_generation_key(self) -> str:
        return f"generation:{self.caller.identity_key}"

    def _caller_category_generation_key(self, category: str) -> str:
        return f"generation:{self.caller.identity_key}:{category}"

    def _increment_generation(self, generation_key: str) -> None:
        try:
            self._cache.incr(generation_key)
        except KeyError:
            # Generation counters must outlive the values they version. An evicted counter
            # restarts, and keys invalidated before it become reachable again, so no expiry.
            self._cache.set(generation_key, 2, ttl=None)
