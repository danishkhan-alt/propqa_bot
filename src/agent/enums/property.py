from enum import Enum


class PropertyCategory(str, Enum):
    """Active rows in public.categories. Value is slug_en. Parents have no parent."""

    RESIDENTIAL = "residential"
    APARTMENT = "apartments"
    VILLA = "villas"
    TOWNHOUSE = "townhouses"
    HOTEL_APARTMENT = "hotel-apartments"
    PENTHOUSE = "penthouse"
    VILLA_COMPOUND = "villa-compound"
    COMMERCIAL = "commercial"
    OFFICE = "offices"
    SHOP = "shops"
    WAREHOUSE = "warehouses"
    COMMERCIAL_PLOT = "commercial-plots"
    LABOUR_CAMP = "labour-camps"
    BUSINESS_CENTER = "business-centers"
    COWORKING_SPACE = "co-working-spaces"
