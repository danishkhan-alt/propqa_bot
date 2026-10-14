"""Agencies and agents who advertise a live listing, matched from public.users.

An agency matches when its company name or its user name contains the typed name, and again
on the brand once legal words are set aside. An agent matches the full person name only:
"John" is not every John Smith.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from agent.grounding.name_matching import NameMatcher, brand_stem, normalize_name

MAX_AGENCY_MATCHES = 25
MAX_AGENT_MATCHES = 10


@dataclass(frozen=True)
class Advertiser:
    user_id: int
    role: str
    company_name: str
    name_en: str
    listing_count: int

    @property
    def title(self) -> str:
        if self.role == "agency":
            return self.company_name or self.name_en
        return self.name_en or self.company_name


class AdvertiserDirectory:
    def __init__(self, advertisers: Iterable[Advertiser] = ()) -> None:
        self._agencies: NameMatcher[int] = NameMatcher()
        self._agents: NameMatcher[int] = NameMatcher()
        self._by_key: dict[tuple[str, int], Advertiser] = {}
        for advertiser in advertisers:
            names = _match_names(advertiser)
            if not names:
                continue
            key = (advertiser.role, advertiser.user_id)
            self._by_key[key] = advertiser
            if advertiser.role == "agency":
                self._agencies.add(advertiser.user_id, names)
            elif advertiser.role == "agent":
                self._agents.add(advertiser.user_id, names)

    def __len__(self) -> int:
        return len(self._by_key)

    def find_agencies(self, phrase: str) -> list[Advertiser]:
        hits = self._agencies.find_containing(phrase)
        if not hits:
            stem = brand_stem(phrase)
            if stem and stem != normalize_name(phrase):
                hits = self._agencies.find_containing(stem)
        return self._ranked(hits, "agency", MAX_AGENCY_MATCHES)

    def find_agents(self, phrase: str) -> list[Advertiser]:
        """The strongest tier only. A first name does not match every longer name that starts with it."""
        hits = self._agents.find_exact(phrase) or self._agents.find_typos(phrase)
        return self._ranked(hits, "agent", MAX_AGENT_MATCHES)

    def _ranked(self, hits, role: str, limit: int) -> list[Advertiser]:
        user_ids = list(dict.fromkeys(hit.key for hit in hits))
        found = [self._by_key[(role, user_id)] for user_id in user_ids if (role, user_id) in self._by_key]
        found.sort(key=lambda advertiser: -advertiser.listing_count)
        return found[:limit]


def advertisers_from_rows(rows: Iterable[dict]) -> list[Advertiser]:
    advertisers: list[Advertiser] = []
    for row in rows:
        if row.get("id") is None:
            continue
        role = str(row.get("role") or "")
        company_name = str(row.get("company_name") or "").strip()
        name_en = str(row.get("name_en") or "").strip()
        if role == "agent" and not name_en:
            continue
        if role == "agency" and not (company_name or name_en):
            continue
        if role not in ("agency", "agent"):
            continue
        advertisers.append(
            Advertiser(
                user_id=int(row["id"]),
                role=role,
                company_name=company_name,
                name_en=name_en,
                listing_count=int(row.get("n") or 0),
            )
        )
    return advertisers


def _match_names(advertiser: Advertiser) -> list[str]:
    if advertiser.role == "agent":
        return [advertiser.name_en] if advertiser.name_en else []
    names = [advertiser.company_name, advertiser.name_en]
    return list(dict.fromkeys(name for name in names if name))
