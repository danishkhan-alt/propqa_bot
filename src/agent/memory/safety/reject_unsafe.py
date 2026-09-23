"""Reject memories that would store SQL, secrets, or a column we do not own."""

from __future__ import annotations

from dataclasses import replace

from agent.memory.models.column_map import ColumnSpec
from agent.memory.safety.never_store import (
    DOTTED,
    EMAIL,
    EMIRATES_ID,
    PHONE,
    PROTECTED,
    SQL,
    THIRD_PARTY,
)
from agent.memory.models.types import MemoryOp

_location_checker = None


class MemoryRejected(ValueError):
    """The extractor offered a memory the store will not keep."""


def set_location_checker(checker) -> None:
    """Tests and the warehouse gazetteer can require ids to exist in locations_v2."""
    global _location_checker
    _location_checker = checker


def redact(text: str) -> str:
    cleaned = EMAIL.sub("[redacted]", text or "")
    cleaned = PHONE.sub("[redacted]", cleaned)
    return EMIRATES_ID.sub("[redacted]", cleaned)


def validate_memory(op: MemoryOp, columns: dict[str, ColumnSpec]) -> MemoryOp:
    """Reject memories that would store SQL, secrets, or a column we do not own.
    
    This function is used to validate the content and evidence of a memory operation.
    It checks for SQL injection, protected information, third-party information, and column ownership.
    It also checks for the value type of the memory operation.

    Args:
        op: The memory operation to validate.
        columns: A dictionary of column specifications.

    Returns:
        The validated memory operation.

    Raises:
        MemoryRejected: If the memory operation is rejected.
    """
    
    content = redact(op.content)
    evidence = redact(op.evidence)
    
    if (
        PROTECTED.search(content)
        or PROTECTED.search(evidence)
        or THIRD_PARTY.search(content)
    ):
        raise MemoryRejected("protected or third-party fact")

    if _looks_like_sql(content, columns) or _looks_like_sql(evidence, columns):
        raise MemoryRejected("sql or table name in content")

    structured = dict(op.structured) if op.structured else None

    if structured and "sql" in structured:
        raise MemoryRejected("sql in structured memory")

    if structured and "col" in structured:
        spec = columns.get(str(structured["col"]))
        if spec is None:
            raise MemoryRejected("unknown column")
        _check_value(spec, structured.get("val"))

    confidence = min(1.0, max(0.0, float(op.confidence)))

    if op.provenance == "inferred":
        confidence = min(confidence, 0.6)

    return replace(
        op,
        content=content,
        evidence=evidence,
        structured=structured,
        confidence=confidence,
    )


def _looks_like_sql(text: str, columns: dict[str, ColumnSpec]) -> bool:
    """Check if the text contains SQL or table names.
    
    This function is used to check if the text contains SQL or table names.
    It checks for SQL injection and table names in the text.
    It also checks for the columns in the text.

    Args:
        text: The text to check.
        columns: A dictionary of column specifications.

    Returns:
        True if the text contains SQL or table names, False otherwise.

    Raises:
        MemoryRejected: If the text contains SQL or table names.
    """
    
    if not text:
        return False
    if SQL.search(text):
        return True
    for match in DOTTED.finditer(text):
        token = match.group(0).lower()
        if (
            token in columns
            or token.startswith("properties.")
            or token.startswith("locations")
        ):
            return True
    return False


def _check_value(spec: ColumnSpec, value) -> None:
    kind = spec.value_type
    if kind == "bool":
        if not isinstance(value, bool):
            raise MemoryRejected("value type")
        return
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise MemoryRejected("value type")
        return
    if kind == "numeric":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MemoryRejected("value type")
        return
    if kind == "text":
        if not isinstance(value, str) or not value.strip():
            raise MemoryRejected("value type")
        return
    if kind == "id_list":
        if not isinstance(value, list) or not value:
            raise MemoryRejected("unresolved id list")
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item <= 0
            for item in value
        ):
            raise MemoryRejected("unresolved id list")
        checker = _location_checker
        if checker is not None and not checker(value):
            raise MemoryRejected("unknown location id")
        return
    raise MemoryRejected("value type")
