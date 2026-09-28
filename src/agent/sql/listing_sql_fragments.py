"""What a live listing is, in SQL, for every statement written in code. `p` is public.properties."""

LISTINGS_TABLE = "public.properties"

ACTIVE_LISTING_CONDITION = "p.status = 'active' AND p.deleted_at IS NULL"
# price_max holds the asking price for sale and rent alike; price_min is a rarely set lower bound.
ASKING_PRICE_SQL = "COALESCE(p.price_max, p.price_min)"

# lat and lng are free text on listings; a pin is only read from two plain, nonzero numbers.
COORDINATE_PATTERN = r"^\s*-?[0-9]+(\.[0-9]+)?\s*$"
LISTING_HAS_PIN_SQL = (
    f"p.lat ~ '{COORDINATE_PATTERN}' AND p.lng ~ '{COORDINATE_PATTERN}' "
    "AND p.lat::float8 <> 0 AND p.lng::float8 <> 0"
)
LISTING_PIN_SQL = "ST_SetSRID(ST_MakePoint(p.lng::float8, p.lat::float8), 4326)"
