"""Fixed lookups from catalog/recipes.yaml, bound from the grounded names.

A recipe answers a common question with SQL that was written and checked once, so the
turn skips drafting. It runs only when every name in the message binds to one of its
parameters; any other name means a narrower question, which the drafted path answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import sqlglot
from sqlglot import exp

from agent.schemas.grounding import Grounding
from catalog import load_recipes


@dataclass(frozen=True)
class RecipeParam:
    name: str
    table: str
    kind: str


@dataclass(frozen=True)
class Recipe:
    id: str
    domains: tuple[str, ...]
    when: str
    purpose: str
    params: tuple[RecipeParam, ...]
    sql: str


@dataclass(frozen=True)
class BoundRecipe:
    recipe: Recipe
    sql: str
    values: dict[str, list[str]]

    def filters(self) -> list[str]:
        """The conditions the user's words set, as `name: value`. The recipe's own are in purpose."""
        return [f"{name}: {', '.join(stored)}" for name, stored in self.values.items()]


@lru_cache(maxsize=1)
def recipes() -> dict[str, Recipe]:
    loaded: dict[str, Recipe] = {}
    for item in load_recipes():
        params = tuple(
            RecipeParam(name=str(name), table=str(spec["table"]).lower(), kind=str(spec["kind"]))
            for name, spec in (item.get("params") or {}).items()
        )
        recipe = Recipe(
            id=str(item["id"]),
            domains=tuple(str(domain) for domain in item.get("domains") or []),
            when=" ".join(str(item.get("when") or "").split()),
            purpose=" ".join(str(item.get("purpose") or "").split()),
            params=params,
            sql=str(item["sql"]).strip(),
        )
        loaded[recipe.id] = recipe
    return loaded


def recipe(recipe_id: str | None) -> Recipe | None:
    return recipes().get(recipe_id) if recipe_id else None


def recipe_index_text() -> str:
    """What the domain router reads: one line per recipe."""
    return "\n".join(f"- {item.id} ({', '.join(item.domains)}): {item.when}" for item in recipes().values())


def bind_recipe(chosen: Recipe, grounding: Grounding | None) -> BoundRecipe | None:
    """The recipe's SQL with each parameter replaced by its stored values, or None.

    Each parameter takes exactly one grounded name, and every grounded name must be taken.
    Values are stored spellings from the warehouse, rendered as quoted literals by sqlglot.
    """
    unused = list(grounding.names) if grounding is not None else []
    if len(unused) != len(chosen.params):
        return None
    values: dict[str, list[str]] = {}
    for param in chosen.params:
        for name in unused:
            stored = sorted(
                {match.value for match in name.stored if match.table == param.table and match.kind == param.kind}
            )
            if stored:
                values[param.name] = stored
                unused.remove(name)
                break
        else:
            return None
    statement = sqlglot.parse_one(chosen.sql, read="postgres")

    def fill(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Placeholder) and node.name in values:
            return exp.Array(expressions=[exp.Literal.string(value) for value in values[node.name]])
        return node

    return BoundRecipe(recipe=chosen, sql=statement.transform(fill).sql(dialect="postgres"), values=values)
