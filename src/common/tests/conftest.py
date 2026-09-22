from __future__ import annotations

import pytest

from common.cache import MemoryCache, set_cache


@pytest.fixture(autouse=True)
def memory_cache():
    backend = MemoryCache()
    set_cache(backend)
    yield backend
    set_cache(None)
