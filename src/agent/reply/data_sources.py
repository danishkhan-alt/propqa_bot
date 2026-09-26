"""The plain-language note under a reply that says which data it came from."""

from __future__ import annotations

FOCUSED_LISTINGS_DATA_NOTE = "the listing's advert and nearby places"

_SOURCE_PHRASE_BY_DOMAIN = {
    "listings": "live asking prices and registered property records",
    "transactions": "registered sales and rent contracts",
    "market": "official price indices and community averages",
    "regulations": "owners-association service charges",
    "developers": "project and developer records",
    "schools": "school ratings and fees",
    "amenities": "parks, healthcare, and building amenities",
    "rta": "metro, roads, and parking",
    "agencies": "licensed brokers and offices",
    "locations": "community records",
}


def describe_data_sources(domain_ids: list) -> str:
    phrases: list[str] = []
    for domain_id in domain_ids:
        phrase = _SOURCE_PHRASE_BY_DOMAIN.get(str(domain_id))
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return "; ".join(phrases)
