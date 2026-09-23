from __future__ import annotations

import pytest

from agent.memory.session.bootstrap import close_memory


@pytest.fixture(autouse=True)
def reset_memory():
    close_memory()
    yield
    close_memory()
