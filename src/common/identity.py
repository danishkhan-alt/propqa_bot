from __future__ import annotations

from dataclasses import dataclass

from common.enums.user_kind import UserKind


@dataclass(frozen=True, slots=True)
class Caller:
    """The person on this request: a registered user or a visitor.

    ``subject_id`` is a user id when registered, and a durable visitor id
    otherwise. Cache keys and rate-limit identities are built from both
    fields so the two populations never share a bucket.
    """

    kind: UserKind
    subject_id: str

    @property
    def is_registered(self) -> bool:
        return self.kind is UserKind.REGISTERED

    @property
    def is_visitor(self) -> bool:
        return self.kind is UserKind.VISITOR

    @property
    def identity_key(self) -> str:
        return f"{self.kind.value}:{self.subject_id}"
