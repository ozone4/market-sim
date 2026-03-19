"""
Buyer agent data models for the market simulation.

Defines BuyerAgent and its constituent profiles: FinancialProfile
(income, savings, debts, equity), PreferenceProfile (what they want),
and BehaviorProfile (urgency, patience, risk). Also defines the
HouseholdType and AgentStatus enums that drive demographic sampling.

All monetary values are in Canadian dollars (CAD).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class HouseholdType(str, Enum):
    SINGLE_YOUNG = "single_young"           # 20-35, single, renter
    COUPLE_NO_KIDS = "couple_no_kids"       # 25-40, couple, may own
    COUPLE_WITH_KIDS = "couple_with_kids"   # 30-50, needs space
    SINGLE_PARENT = "single_parent"         # constrained budget
    DOWNSIZER = "downsizer"                 # 55+, selling large home
    RETIREE = "retiree"                     # 65+, equity-rich, patient
    INVESTOR = "investor"                   # ROI-driven, may own multiple
    NEW_TO_AREA = "new_to_area"             # Relocating, urgent, less local knowledge


class AgentStatus(str, Enum):
    ENTERING = "entering"
    SEARCHING = "searching"
    SHORTLISTING = "shortlisting"
    BIDDING = "bidding"
    WON = "won"
    LOST_BID = "lost_bid"           # Lost this round, will search again
    ADJUSTING = "adjusting"         # Expanding criteria after losses
    EXITED = "exited"               # Left the market


class FinancialProfile(BaseModel):
    annual_income: float                    # Gross household income
    savings: float                          # Available for down payment
    existing_monthly_debts: float = 0.0     # Car payments, student loans, etc.
    current_home_value: float = 0.0         # 0 if renter
    current_mortgage_balance: float = 0.0   # Remaining mortgage on current home
    is_first_time_buyer: bool = True

    @property
    def available_equity(self) -> float:
        """Net equity from current home after 7% selling costs."""
        if self.current_home_value <= 0:
            return 0.0
        equity = self.current_home_value - self.current_mortgage_balance
        return max(0.0, equity * 0.93)  # 7% selling costs (agent + legal + tax)

    @property
    def total_down_payment(self) -> float:
        return self.savings + self.available_equity


class PreferenceProfile(BaseModel):
    """What the agent wants, weighted 0-1. Weights should roughly sum to 1."""
    location_weight: float = 0.25
    size_weight: float = 0.25
    condition_weight: float = 0.20
    commute_weight: float = 0.15
    features_weight: float = 0.15

    # Hard constraints
    min_bedrooms: int = 1
    max_price: Optional[float] = None      # Computed from financial qualification
    preferred_property_types: list[str] = Field(default_factory=list)  # empty = any
    preferred_neighbourhoods: list[str] = Field(default_factory=list)  # empty = any
    max_commute_km: float = 50.0
    needs_garage: bool = False
    needs_suite: bool = False


class BehaviorProfile(BaseModel):
    urgency: float = Field(ge=0, le=1, default=0.5)
    risk_tolerance: float = Field(ge=0, le=1, default=0.5)
    patience_weeks: int = 26          # How long before exiting market
    adjustment_after_losses: int = 3  # Losses before expanding criteria
    max_bid_stretch: float = 0.05     # How far above comfortable max they'll go (0.05 = 5%)


class BuyerAgent(BaseModel):
    id: str
    household_type: HouseholdType
    financial: FinancialProfile
    preferences: PreferenceProfile
    behavior: BehaviorProfile

    # State (changes during simulation)
    status: AgentStatus = AgentStatus.ENTERING
    weeks_in_market: int = 0
    bid_losses: int = 0
    properties_viewed: list[str] = Field(default_factory=list)  # folio_ids
    current_bid_target: Optional[str] = None  # folio_id of property they're bidding on
    entry_week: int = 0
