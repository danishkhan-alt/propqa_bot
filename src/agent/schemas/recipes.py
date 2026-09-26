"""Vetted SQL recipes from the catalog, and a recipe bound to the user's values."""

from __future__ import annotations

from dataclasses import dataclass


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
