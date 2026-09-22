from __future__ import annotations

from catalog import domain_prompt, list_domains, load_domain, load_prompt


def domain_blurbs() -> str:
    """id + one-line description. This is all the query router sees of the catalog."""
    lines = [f"- {domain['id']}: {domain.get('description', '').strip()}" for domain in list_domains()]
    return "\n".join(lines)


def domain_index_text() -> str:
    """Compact index for the domain router. No columns."""
    lines: list[str] = []
    for domain in list_domains():
        synonyms = ", ".join(domain.get("synonyms") or [])
        description = " ".join(str(domain.get("description") or "").split())
        lines.append(
            f"- {domain['id']}: {domain.get('name', '')}. {description} "
            f"Synonyms: {synonyms}. Tables: {domain.get('table_count', 0)}."
        )
    return "\n".join(lines)


def table_count(domain_ids: list[str]) -> int:
    counts = {domain["id"]: int(domain.get("table_count") or 0) for domain in list_domains()}
    return sum(counts.get(domain_id, 0) for domain_id in domain_ids)


def render_catalog(domain_ids: list[str], join_ids: list[str]) -> str:
    """Full YAML for primary packs. Joins are full packs until a join-only loader exists."""
    chunks: list[str] = []
    if domain_ids:
        chunks.append(load_prompt(domain_ids))
    for join_id in join_ids:
        chunks.append(f"# join: {join_id}\n{domain_prompt(load_domain(join_id))}")
    return "\n---\n".join(chunks)
