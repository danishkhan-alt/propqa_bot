"""The strict JSON schema a structured call is constrained to."""

from __future__ import annotations

from pydantic import BaseModel


def build_strict_output_schema(model: type[BaseModel]) -> dict:
    """The JSON schema a structured call is constrained to, with every field required.

    The API allows at most 24 optional and 16 union-typed fields, and each optional field
    makes the grammar slower to compile. Here every field is required, nullable ones as
    unions, so the model always writes each field. Python defaults still apply wherever
    code builds these models. Objects are closed, as OpenAI's strict mode requires.
    """
    schema = model.model_json_schema(mode="serialization")
    defs = schema.get("$defs", {})
    shaped = _inline_annotated_refs({key: value for key, value in schema.items() if key != "$defs"}, defs)
    used = _referenced_defs(shaped, defs)
    if used:
        shaped["$defs"] = {name: _inline_annotated_refs(defs[name], defs) for name in used}
    return _require_every_property(shaped)


def _referenced_defs(node, defs: dict) -> list[str]:
    """Definitions still reached by a $ref, following refs inside definitions too."""
    found: list[str] = []
    pending = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, list):
            pending.extend(current)
        elif isinstance(current, dict):
            ref = current.get("$ref")
            name = ref.removeprefix("#/$defs/") if isinstance(ref, str) else None
            if name in defs and name not in found:
                found.append(name)
                pending.append(_inline_annotated_refs(defs[name], defs))
            pending.extend(current.values())
    return found


def _inline_annotated_refs(node, defs: dict):
    """Strict mode rejects a $ref with sibling keywords, so inline that definition instead.

    The field's description is kept; its default is dropped, since every field is written.
    """
    if isinstance(node, list):
        return [_inline_annotated_refs(item, defs) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and len(node) > 1 and ref.startswith("#/$defs/"):
        target = defs.get(ref.removeprefix("#/$defs/"))
        if isinstance(target, dict):
            siblings = {key: value for key, value in node.items() if key not in ("$ref", "default")}
            return _inline_annotated_refs({**target, **siblings}, defs)
    return {key: _inline_annotated_refs(value, defs) for key, value in node.items()}


def _require_every_property(node):
    if isinstance(node, dict):
        shaped = {key: _require_every_property(value) for key, value in node.items()}
        if isinstance(shaped.get("properties"), dict):
            shaped["required"] = list(shaped["properties"])
            shaped["additionalProperties"] = False
        return shaped
    if isinstance(node, list):
        return [_require_every_property(item) for item in node]
    return node
