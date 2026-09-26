"""The model's verdict on how a follow-up message relates to the current search."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class FollowUpClassification(BaseModel):
    """Haiku's decision when a follow-up is not one of the known comparatives."""

    kind: Literal["refine", "pivot", "new"]
