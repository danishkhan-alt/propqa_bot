from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from common.errors import InvalidRequestBody

Schema = TypeVar("Schema", bound=BaseModel)


async def parse_json_body(request: Request) -> dict:
    raw_body = await request.body()
    if not raw_body or not raw_body.strip():
        raise InvalidRequestBody("The request body is required.")

    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        raise InvalidRequestBody("The request body is not valid JSON.") from None


def validate_against_schema(schema: type[Schema], raw: Any) -> Schema:
    try:
        return schema.model_validate(raw)
    except ValidationError as exc:
        fields = [
            {"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]}
            for e in exc.errors()
        ]
        detail = "; ".join(f"{f['field']}: {f['problem']}" for f in fields)
        raise InvalidRequestBody(detail, fields) from None


async def parse_query(request: Request, schema: type[Schema]) -> Schema:
    return validate_against_schema(schema, dict(request.query_params))
