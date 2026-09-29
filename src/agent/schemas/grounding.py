from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent.enums.listing import MentionKind
from agent.schemas.routes import unwrap_checkpoint_payload


class GroundedPlace(BaseModel):
    """The place a name was taken to mean, with every way a listing can point at it."""

    title: str
    is_approximate: bool = False
    alternatives: list[str] = Field(default_factory=list)
    v2_ids: list[int] = Field(default_factory=list)
    legacy_ids: list[int] = Field(default_factory=list)
    address_names: list[str] = Field(default_factory=list)


class StoredMatch(BaseModel):
    """A stored spelling of the name, in one column."""

    table: str
    column: str
    value: str
    kind: str
    same_place_as: str | None = None


class GroundedName(BaseModel):
    text: str
    kind: MentionKind
    place: GroundedPlace | None = None
    stored: list[StoredMatch] = Field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return self.place is not None or bool(self.stored)


class Grounding(BaseModel):
    """What each name in the message was matched to. Cleared before the checkpoint."""

    names: list[GroundedName] = Field(default_factory=list)

    def unresolved_names(self) -> list[str]:
        return [name.text for name in self.names if not name.is_resolved]

    def stored_values_in(self, table: str, kind: str) -> list[str]:
        """Stored values of one kind in one table, e.g. developers in public.properties."""
        return [
            match.value
            for name in self.names
            for match in name.stored
            if match.table == table and match.kind == kind
        ]

    def for_sql_prompt(self) -> list[dict[str, Any]]:
        """What the SQL model is told: which stored value each name means, per column."""
        view: list[dict[str, Any]] = []
        for name in self.names:
            entry: dict[str, Any] = {"name": name.text}
            if name.place is not None:
                entry["means"] = name.place.title
                if name.place.is_approximate:
                    entry["approximate"] = True
            if name.stored:
                entry["stored_values"] = [
                    {
                        "column": f"{match.table}.{match.column}",
                        "value": match.value,
                        **({"same_place_as": match.same_place_as} if match.same_place_as else {}),
                    }
                    for match in name.stored
                ]
            if not name.is_resolved:
                entry["unresolved"] = True
            view.append(entry)
        return view


def as_grounding(value: Grounding | dict[str, Any] | None) -> Grounding | None:
    if value is None:
        return None
    if isinstance(value, Grounding):
        return value

    return Grounding.model_validate(unwrap_checkpoint_payload(value))
