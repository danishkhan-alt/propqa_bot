from __future__ import annotations

import pytest

from agent.memory.session.backends import close_memory_backends


@pytest.fixture(autouse=True)
def reset_memory():
    close_memory_backends()
    yield
    close_memory_backends()
