"""Fixed lookups from catalog/recipes.yaml, bound from the grounded names.

A recipe answers a common question with SQL that was written and checked once, so the
turn skips drafting. It runs only when every name in the message binds to one of its
parameters; any other name means a narrower question, which the drafted path answers.
"""

from __future__ import annotations

from functools import lru_cache

import sqlglot
from sqlglot import exp

from agent.schemas.grounding import Grounding
from agent.schemas.recipes import BoundRecipe, Recipe, RecipeParam
from catalog import load_recipes


@lru_cache(maxsize=1)
def load_recipes_by_id() -> dict[str, Recipe]:
    loaded: dict[str, Recipe] = {}
    for item in load_recipes():
        params = tuple(
            RecipeParam(
                name=str(name),
                table=str(spec["table"]).lower(),
                kind=str(spec["kind"]),
                many=bool(spec.get("many")),
            )
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


def get_recipe(recipe_id: str | None) -> Recipe | None:
    return load_recipes_by_id().get(recipe_id) if recipe_id else None


def recipe_index_text() -> str:
    """What the domain router reads: one line per recipe."""
    return "\n".join(f"- {item.id} ({', '.join(item.domains)}): {item.when}" for item in load_recipes_by_id().values())


def _stored_for(name, param: RecipeParam) -> list[str]:
    return sorted(
        {match.value for match in name.stored if match.table == param.table and match.kind == param.kind}
    )


def bind_recipe(chosen: Recipe, grounding: Grounding | None) -> BoundRecipe | None:
    """The recipe's SQL with each parameter replaced by its stored values, or None.

    A parameter takes exactly one grounded name, unless it is marked many, in which case it
    takes every remaining name of its table and kind and needs at least two. Every grounded
    name must be taken. Values are stored spellings from the warehouse, rendered as quoted
    literals by sqlglot.
    """
    unused = list(grounding.names) if grounding is not None else []
    values: dict[str, list[str]] = {}
    for param in chosen.params:
        if param.many:
            continue
        for name in unused:
            stored = _stored_for(name, param)
            if stored:
                values[param.name] = stored
                unused.remove(name)
                break
        else:
            return None
    for param in chosen.params:
        if not param.many:
            continue
        taken = []
        collected: list[str] = []
        for name in unused:
            stored = _stored_for(name, param)
            if stored:
                taken.append(name)
                collected.extend(stored)
        if len(taken) < 2:
            return None
        for name in taken:
            unused.remove(name)
        values[param.name] = sorted(set(collected))
    if unused:
        return None
    statement = sqlglot.parse_one(chosen.sql, read="postgres")

    def fill(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Placeholder) and node.name in values:
            return exp.Array(expressions=[exp.Literal.string(value) for value in values[node.name]])
        return node

    return BoundRecipe(recipe=chosen, sql=statement.transform(fill).sql(dialect="postgres"), values=values)
