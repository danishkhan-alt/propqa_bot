from __future__ import annotations

from pathlib import Path

import yaml

CATALOG_DIR = Path(__file__).resolve().parent
DOMAINS_DIR = CATALOG_DIR / "domains"
INDEX_PATH = DOMAINS_DIR / "index.yaml"


def list_domains() -> list[dict]:
    """Compact domain index for the query / domain routers."""
    payload = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8"))
    return list(payload.get("domains") or [])


def load_domain(domain_id: str) -> dict:
    """Full SQL-agent catalog for one domain."""
    path = DOMAINS_DIR / f"{domain_id}.yaml"
    if not path.exists():
        known = ", ".join(d["id"] for d in list_domains())
        raise KeyError(f"Unknown domain '{domain_id}'. Known: {known}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_domains(domain_ids: list[str]) -> list[dict]:
    return [load_domain(domain_id) for domain_id in domain_ids]


def domain_prompt(domain: dict) -> str:
    """YAML fragment the SQL agent can be given as schema context."""
    return yaml.safe_dump(domain, sort_keys=False, allow_unicode=True, width=100)


def load_prompt(domain_ids: list[str]) -> str:
    parts = [domain_prompt(load_domain(domain_id)) for domain_id in domain_ids]
    return "\n---\n".join(parts)
