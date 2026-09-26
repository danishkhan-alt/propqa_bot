"""Client for TypeSafe's System One API (Jev): typed judgments with probabilities.

https://docs.typesafe.ai/api
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from common.logger import get_logger

logger = get_logger("agent.typesafe")

ENDPOINT = "https://api.typesafe.ai/v1/systemone"

# Rate limited or overloaded, or a server error: worth one more try.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504, 529})
_RETRY_DELAY_SECONDS = 0.4


class TypeSafeError(RuntimeError):
    """The call failed or returned an unusable body. Callers fall back to another router."""


class SystemOneClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("TypeSafe needs an API key; set JEV_API_KEY")
        self._model = model
        self._http = httpx.Client(
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    def ask(self, *, state: Any, questions: dict[str, dict], run_name: str) -> dict[str, dict]:
        """Answer every question over one state. Returns answers keyed by question id."""
        body = {"model": self._model, "state": state, "questions": questions}
        started = time.perf_counter()
        try:
            payload = self._post(body).json()
        except ValueError as exc:
            raise TypeSafeError("response was not JSON") from exc
        if not isinstance(payload, dict):
            raise TypeSafeError("response was not an object")
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise TypeSafeError("response had no answers")
        missing = set(questions) - set(answers)
        if missing:
            raise TypeSafeError(f"answers missing for {sorted(missing)}")
        logger.info(
            "typesafe.call",
            extra={
                "extra_data": {
                    "run_name": run_name,
                    "model": payload.get("model"),
                    "questions": len(questions),
                    "usage": payload.get("usage"),
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                }
            },
        )
        return answers

    def _post(self, body: dict) -> httpx.Response:
        error: Exception | None = None
        for attempt in range(2):
            if attempt:
                time.sleep(_RETRY_DELAY_SECONDS)
            try:
                response = self._http.post(ENDPOINT, json=body)
            except httpx.HTTPError as exc:
                error = exc
                continue
            if response.status_code == 200:
                return response
            error = TypeSafeError(f"status {response.status_code}: {response.text[:200]}")
            if response.status_code not in _RETRYABLE_STATUS_CODES:
                break
        raise TypeSafeError(str(error)) from error
