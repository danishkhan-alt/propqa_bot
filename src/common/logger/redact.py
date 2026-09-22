from __future__ import annotations

#: Header names whose values must never reach a log file, matched
#: case-insensitively. Substrings rather than exact names, so a new
#: ``X-Shopify-Access-Token`` is caught by "token" without an edit here.
SENSITIVE_HEADER_PARTS = (
    "authorization",
    "cookie",
    "token",
    "secret",
    "password",
    "api-key",
    "apikey",
    "signature",
    "x-api-key",
)


def redact_token(value: str | None, visible_chars: int = 4) -> str:
    """Keep just enough to tell two credentials apart, and no more.

    Four characters, not ten. A marketplace token is structured -- eBay's
    begins ``v^1.1#i^1#f^0#`` -- so a ten-character prefix can be entirely
    format and leak nothing, or be ten real characters of a short secret.
    Four is enough to correlate two log lines, which is the only reason to
    show any of it.
    """
    if not value:
        return "<empty>"
    if len(value) <= visible_chars * 2:
        return "<redacted>"
    return f"{value[:visible_chars]}...<redacted:{len(value)}>"


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Copy of the headers with anything credential-shaped masked."""
    return {
        key: redact_token(value) if _is_sensitive(key) else value
        for key, value in headers.items()
    }


def _is_sensitive(header_name: str) -> bool:
    lowered = header_name.lower()
    return any(part in lowered for part in SENSITIVE_HEADER_PARTS)
