"""What a live listing is, in SQL, for every statement written in code. `p` is public.properties."""

LISTINGS_TABLE = "public.properties"

ACTIVE_LISTING_CONDITION = "p.status = 'active' AND p.deleted_at IS NULL"
# price_max holds the asking price for sale and rent alike; price_min is a rarely set lower bound.
ASKING_PRICE_SQL = "COALESCE(p.price_max, p.price_min)"
