"""What a live listing is, in SQL, for every statement written in code. `p` is public.properties."""

LISTINGS_TABLE = "public.properties"

ACTIVE_LISTING_CONDITION = "p.status = 'active' AND p.deleted_at IS NULL"
# Bound parameter only. `{param}` is the placeholder name, never the user's words.
TEXT_SEARCH_CONDITION = "p.search_vector @@ websearch_to_tsquery('english', %({param})s)"
TEXT_SEARCH_RANK = "ts_rank(p.search_vector, websearch_to_tsquery('english', %({param})s))"
# price_max holds the asking price for sale and rent alike; price_min is a rarely set lower bound.
ASKING_PRICE_SQL = "COALESCE(p.price_max, p.price_min)"
# The contact sheet treats verification_status approved as a verified user. public.users has no
# confirmed is_active column, so the check does not filter on one.
VERIFIED_AGENT_CONDITION = (
    "EXISTS (SELECT 1 FROM public.users vu "
    "WHERE vu.id = p.user_id AND vu.verification_status = 'approved' AND vu.deleted_at IS NULL)"
)

# lat and lng are free text on listings; a pin is only read from two plain, nonzero numbers.
COORDINATE_PATTERN = r"^\s*-?[0-9]+(\.[0-9]+)?\s*$"
LISTING_HAS_PIN_SQL = (
    f"p.lat ~ '{COORDINATE_PATTERN}' AND p.lng ~ '{COORDINATE_PATTERN}' "
    "AND p.lat::float8 <> 0 AND p.lng::float8 <> 0"
)
LISTING_PIN_SQL = "ST_SetSRID(ST_MakePoint(p.lng::float8, p.lat::float8), 4326)"
