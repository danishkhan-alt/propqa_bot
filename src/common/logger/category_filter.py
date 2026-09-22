import logging


class CategoryFilter(logging.Filter):
    """Route log records to handlers based on logger name prefixes."""

    def __init__(self, prefixes: list[str]) -> None:
        super().__init__()
        self._prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return any(record.name.startswith(p) for p in self._prefixes)
