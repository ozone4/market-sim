"""
Property data models for the BC Assessment-based market simulation.

Defines the core domain objects: Property (physical attributes),
Location (spatial context), Features (boolean amenities), Listing
(a property actively on the market), and supporting enums.

All monetary values are in Canadian dollars (CAD).
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PropertyType(str, Enum):
    SFD = "single_family_detached"
    TOWNHOUSE = "townhouse"
    CONDO = "condo"
    DUPLEX = "duplex"
    MANUFACTURED = "manufactured"


class Condition(str, Enum):
    POOR = "poor"
    FAIR = "fair"
    AVERAGE = "average"
    GOOD = "good"
    EXCELLENT = "excellent"


class Features(BaseModel):
    view: bool = False
    waterfront: bool = False
    suite: bool = False
    garage: bool = False
    corner_lot: bool = False
    fireplace: bool = False
    pool: bool = False
    renovated_recent: bool = False  # Major reno in last 10 years


class Location(BaseModel):
    neighbourhood: str
    municipality: str = "Victoria"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    walk_score: Optional[float] = None       # 0-100
    transit_score: Optional[float] = None    # 0-100
    school_proximity: Optional[float] = None  # km to nearest school


class Property(BaseModel):
    folio_id: str
    property_type: PropertyType
    assessed_value: float
    bedrooms: int
    bathrooms: float
    floor_area: float        # sq ft
    lot_size: float          # sq ft
    year_built: int
    condition: Condition
    location: Location
    features: Features = Field(default_factory=Features)
    annual_taxes: float = 0.0


class ListingStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SOLD = "sold"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class PriceReduction(BaseModel):
    week: int               # Simulation week when reduction happened
    old_price: float
    new_price: float
    reason: str = "days_on_market"


class Listing(BaseModel):
    property: Property
    asking_price: float
    listed_week: int = 0
    days_on_market: int = 0
    status: ListingStatus = ListingStatus.ACTIVE
    price_reductions: list[PriceReduction] = Field(default_factory=list)
    offers_received: int = 0

    @property
    def current_asking(self) -> float:
        """Current asking price, reflecting any reductions."""
        if self.price_reductions:
            return self.price_reductions[-1].new_price
        return self.asking_price
