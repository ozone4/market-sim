# Phase 1 — Foundation: Models, Financial Math, Agent Generator, Time Engine

You are building Phase 1 of a multi-agent real estate market simulation at ~/Projects/market-sim/

**Read DESIGN.md first** — it is the authoritative specification. This prompt fills in implementation details.

## What to build

### 1. Property Models — `sim/properties/models.py`

```python
from __future__ import annotations
from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import numpy as np

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
    school_proximity: Optional[float] = None # km to nearest school

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
        if self.price_reductions:
            return self.price_reductions[-1].new_price
        return self.asking_price
```

### 2. Agent Models — `sim/agents/models.py`

```python
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
```

### 3. Financial Math — `sim/agents/financial.py`

This is THE critical module. All mortgage math must be correct for Canadian rules.

```python
"""
Canadian mortgage qualification calculator.

Implements OSFI B-20 stress test rules, CMHC insurance thresholds,
GDS/TDS ratio limits, and amortization calculations.

All rates are annual. All amounts in CAD.
"""

# --- Constants ---
GDS_LIMIT = 0.32              # Gross Debt Service ratio limit
TDS_LIMIT = 0.40              # Total Debt Service ratio limit  
STRESS_TEST_FLOOR = 0.0525    # Minimum qualifying rate (5.25%)
STRESS_TEST_BUFFER = 0.02     # Contract rate + 2%
PROPERTY_TAX_RATE = 0.004     # Approx 0.4% of value annually (Victoria avg)
MONTHLY_HEAT = 175.0          # Standard heating cost estimate
CMHC_THRESHOLD = 0.20         # 20% down = no insurance needed

# CMHC insurance premiums (% of mortgage, by LTV band)
CMHC_PREMIUMS = {
    (0.05, 0.0999): 0.0400,   # 5-9.99% down → 4.00% premium
    (0.10, 0.1499): 0.0310,   # 10-14.99% → 3.10%
    (0.15, 0.1999): 0.0280,   # 15-19.99% → 2.80%
}

def calculate_stress_test_rate(contract_rate: float) -> float:
    """Qualifying rate = max(contract_rate + 2%, 5.25%)"""
    return max(contract_rate + STRESS_TEST_BUFFER, STRESS_TEST_FLOOR)

def calculate_monthly_payment(principal: float, annual_rate: float, amortization_years: int = 25) -> float:
    """
    Monthly mortgage payment using Canadian semi-annual compounding.
    
    Canadian mortgages compound semi-annually, not monthly.
    Effective monthly rate = (1 + annual_rate/2)^(1/6) - 1
    """
    if annual_rate <= 0 or principal <= 0:
        return 0.0
    semi_annual = annual_rate / 2
    monthly_rate = (1 + semi_annual) ** (1/6) - 1
    n = amortization_years * 12
    payment = principal * (monthly_rate * (1 + monthly_rate)**n) / ((1 + monthly_rate)**n - 1)
    return payment

def calculate_cmhc_premium(purchase_price: float, down_payment: float) -> float:
    """CMHC insurance premium. Returns 0 if down payment >= 20%."""
    if purchase_price <= 0:
        return 0.0
    ltv_ratio = 1 - (down_payment / purchase_price)
    if ltv_ratio <= (1 - CMHC_THRESHOLD):
        return 0.0
    dp_pct = down_payment / purchase_price
    for (low, high), premium_rate in CMHC_PREMIUMS.items():
        if low <= dp_pct <= high:
            mortgage = purchase_price - down_payment
            return mortgage * premium_rate
    return 0.0

def calculate_max_purchase_price(
    annual_income: float,
    down_payment: float,
    monthly_debts: float = 0.0,
    contract_rate: float = 0.05,
    property_tax_rate: float = PROPERTY_TAX_RATE,
    amortization_years: int = 25,
) -> float:
    """
    Maximum purchase price given income, down payment, and debts.
    
    Uses GDS and TDS constraints with stress test rate.
    Returns the lower of the two limits + down payment.
    
    Iterative solver: binary search for max mortgage where both
    GDS and TDS are satisfied at the stress test rate.
    """
    qualifying_rate = calculate_stress_test_rate(contract_rate)
    gross_monthly = annual_income / 12
    
    # Binary search for max mortgage
    low, high = 0.0, annual_income * 8  # Upper bound: 8x income
    
    for _ in range(50):  # 50 iterations = plenty of precision
        mid = (low + high) / 2
        purchase_price = mid + down_payment
        
        monthly_payment = calculate_monthly_payment(mid, qualifying_rate, amortization_years)
        monthly_tax = purchase_price * property_tax_rate / 12
        
        gds = (monthly_payment + monthly_tax + MONTHLY_HEAT) / gross_monthly if gross_monthly > 0 else 999
        tds = (monthly_payment + monthly_tax + MONTHLY_HEAT + monthly_debts) / gross_monthly if gross_monthly > 0 else 999
        
        if gds <= GDS_LIMIT and tds <= TDS_LIMIT:
            low = mid
        else:
            high = mid
    
    max_mortgage = low
    # Add CMHC premium to mortgage if applicable
    purchase_price = max_mortgage + down_payment
    cmhc = calculate_cmhc_premium(purchase_price, down_payment)
    if cmhc > 0:
        # CMHC premium is added to mortgage — need to re-check qualification
        # with larger mortgage. Simplification: reduce max purchase by premium amount.
        purchase_price -= cmhc
    
    return max(0.0, purchase_price)

def qualifies_for_property(
    agent_financial: "FinancialProfile",
    property_price: float,
    contract_rate: float = 0.05,
) -> tuple[bool, str]:
    """
    Check if an agent can qualify to purchase at the given price.
    
    Returns (qualified: bool, reason: str).
    Reason is "qualified" or describes why not.
    """
    down = agent_financial.total_down_payment
    
    # Minimum down payment check (Canadian rules)
    # First $500K: 5%, $500K-$1M: 10% on portion above $500K, $1M+: 20%
    if property_price <= 500_000:
        min_down = property_price * 0.05
    elif property_price <= 1_000_000:
        min_down = 500_000 * 0.05 + (property_price - 500_000) * 0.10
    else:
        min_down = property_price * 0.20
    
    if down < min_down:
        return False, f"insufficient_down_payment (need ${min_down:,.0f}, have ${down:,.0f})"
    
    max_price = calculate_max_purchase_price(
        annual_income=agent_financial.annual_income,
        down_payment=down,
        monthly_debts=agent_financial.existing_monthly_debts,
        contract_rate=contract_rate,
    )
    
    if property_price > max_price:
        return False, f"exceeds_max_qualification (max ${max_price:,.0f})"
    
    return True, "qualified"
```

### 4. Agent Generator — `sim/agents/generator.py`

Generate demographically realistic agents from census-derived distributions.

```python
"""
Generate buyer agents from demographic distributions.

Uses StatsCan-derived income and household type distributions for
Greater Victoria CMA (Census Metropolitan Area).

All distributions are parameterized and can be overridden for
different regions or scenarios.
"""

# Greater Victoria CMA income distribution (2021 Census, adjusted to 2024 dollars)
# Source: StatsCan Table 11-10-0190-01, inflated ~12% for 2021→2024
VICTORIA_INCOME_DISTRIBUTION = {
    # (min, max): fraction of households
    (30_000, 50_000): 0.15,
    (50_000, 75_000): 0.20,
    (75_000, 100_000): 0.20,
    (100_000, 125_000): 0.15,
    (125_000, 150_000): 0.12,
    (150_000, 200_000): 0.10,
    (200_000, 300_000): 0.06,
    (300_000, 500_000): 0.02,
}

# Household type distribution (Census 2021, Victoria CMA)
VICTORIA_HOUSEHOLD_DISTRIBUTION = {
    HouseholdType.SINGLE_YOUNG: 0.12,
    HouseholdType.COUPLE_NO_KIDS: 0.22,
    HouseholdType.COUPLE_WITH_KIDS: 0.20,
    HouseholdType.SINGLE_PARENT: 0.08,
    HouseholdType.DOWNSIZER: 0.12,
    HouseholdType.RETIREE: 0.10,
    HouseholdType.INVESTOR: 0.10,
    HouseholdType.NEW_TO_AREA: 0.06,
}

# Savings rate by income quintile (rough estimate — savings = years × rate × income)
# Assumes average 5-10 years of saving for home purchase
SAVINGS_MULTIPLIER = {
    1: 0.5,   # Bottom quintile: 0.5× annual income in savings
    2: 0.8,
    3: 1.2,
    4: 1.8,
    5: 3.0,   # Top quintile: 3× annual income
}
```

For each household type, define:
- Income distribution (which quintiles they draw from)
- Savings behavior
- Existing debt likelihood
- Current homeownership probability (for equity calculation)
- Preference profiles (min bedrooms, type preferences, neighbourhood preferences)
- Behavior profiles (urgency, patience, risk tolerance)

The generator should:
1. Accept `num_agents`, `rng: np.random.Generator`, and optional distribution overrides
2. For each agent: sample household type → sample income → compute savings → compute debts → generate preferences → generate behavior
3. Compute `max_purchase_price` for each agent during generation (so we know their ceiling)
4. Return `list[BuyerAgent]`

### 5. Time Engine — `sim/market/clock.py`

```python
"""
Simulation clock — manages weekly time steps.

The simulation runs in discrete weekly ticks. Each tick represents
one week of market activity. The clock tracks:
- Current week number
- Calendar date (for seasonal effects)
- Events scheduled for future weeks
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

@dataclass
class SimulationClock:
    start_date: date
    current_week: int = 0
    
    @property
    def current_date(self) -> date:
        return self.start_date + timedelta(weeks=self.current_week)
    
    @property
    def season(self) -> str:
        month = self.current_date.month
        if month in (3, 4, 5):
            return "spring"
        elif month in (6, 7, 8):
            return "summer"
        elif month in (9, 10, 11):
            return "fall"
        return "winter"
    
    @property
    def is_peak_season(self) -> bool:
        """Spring/early summer = peak real estate season in BC."""
        return self.current_date.month in (3, 4, 5, 6)
    
    def tick(self) -> int:
        self.current_week += 1
        return self.current_week
```

### 6. Market Inventory — `sim/market/inventory.py`

```python
"""
Market inventory manager.

Tracks all listings, their status, days on market, and price reductions.
Handles new listings entering, sold properties leaving, and expired listings.
"""
```

Key methods:
- `add_listing(property, asking_price, week)` — new listing enters market
- `get_active_listings()` → list of active Listing objects
- `mark_sold(folio_id, sale_price, week, buyer_id)`
- `mark_expired(folio_id, week)`
- `apply_price_reductions(week, reduction_rules)` — auto-reduce stale listings
- `tick(week)` — increment DOM for all active listings
- `get_stats()` → MarketStats (active count, avg DOM, avg asking, etc.)

Default price reduction rules:
- After 21 days (3 weeks): reduce 2%
- After 42 days (6 weeks): reduce another 3%
- After 63 days (9 weeks): reduce another 3%
- After 90 days (13 weeks): expire listing

### 7. Macro Shocks — `sim/market/shocks.py`

```python
class ShockType(str, Enum):
    RATE_CHANGE = "rate_change"
    RECESSION = "recession"
    INVENTORY_SURGE = "inventory_surge"
    SEASONAL = "seasonal"

@dataclass
class MacroShock:
    week: int
    shock_type: ShockType
    params: dict  # Type-specific parameters
    
class ShockSchedule:
    """Pre-built shock schedules for common scenarios."""
    
    @staticmethod
    def stable_market(contract_rate: float = 0.05) -> list[MacroShock]:
        """No shocks — stable conditions throughout."""
        return []
    
    @staticmethod
    def rate_hike_scenario(
        start_rate: float = 0.05,
        hike_bps: int = 25,
        hike_weeks: list[int] = [8, 16],
    ) -> list[MacroShock]:
        """Rate increases at specified weeks."""
        ...
    
    @staticmethod  
    def recession_scenario(onset_week: int = 12, severity: float = 0.10) -> list[MacroShock]:
        """Recession: income drops, some agents exit, inventory rises."""
        ...
```

### 8. Sample Data — `data/properties/sample_victoria.json`

Create 30 properties across 4 Victoria-area neighbourhoods (Oak Bay, Saanich East, Langford, View Royal).
Mix of SFD, townhouse, condo. Range $450K-$1.8M assessed value.
Realistic for 2024 Greater Victoria market.

Include a few obvious test cases:
- One clearly underpriced property (great neighbourhood, low assessed value relative to comps)
- One clearly overpriced property (poor condition, high assessed value)
- One average property (market consensus should cluster around assessed value)

### 9. Property Loader — `sim/properties/loader.py`

Load from JSON file. Simple for now, extensible to CSV/database later.

### 10. Package structure

Create all `__init__.py` files. The top-level `sim/__init__.py` should export key classes:

```python
from sim.properties.models import Property, Listing, PropertyType, Condition
from sim.agents.models import BuyerAgent, HouseholdType, AgentStatus
from sim.agents.financial import calculate_max_purchase_price, qualifies_for_property
from sim.agents.generator import generate_buyer_pool
from sim.market.clock import SimulationClock
from sim.market.inventory import MarketInventory
```

### 11. Tests — `tests/`

Write comprehensive tests. Target: 30+ tests.

**tests/test_financial.py** (most critical — these must be right):
- test_monthly_payment_basic — known mortgage, verify payment
- test_monthly_payment_zero_rate — edge case
- test_stress_test_rate_above_floor — contract 4% → qualify at 6%
- test_stress_test_rate_below_floor — contract 2% → qualify at 5.25%
- test_max_purchase_gds_limited — high income, no debts, GDS is binding
- test_max_purchase_tds_limited — moderate income, high debts, TDS is binding
- test_cmhc_premium_20pct_down — no premium
- test_cmhc_premium_10pct_down — correct premium band
- test_cmhc_premium_5pct_down — correct premium band
- test_min_down_payment_under_500k — 5% required
- test_min_down_payment_500k_to_1m — split threshold
- test_min_down_payment_over_1m — 20% required
- test_qualifies_for_affordable_property — should pass
- test_rejects_unaffordable_property — should fail with reason
- test_first_time_buyer_no_equity — savings only
- test_move_up_buyer_with_equity — equity from current home

**tests/test_generator.py:**
- test_generates_correct_count
- test_household_distribution_approximate — proportions within ±5% of target
- test_all_agents_have_max_price — financial qualification computed
- test_deterministic_with_seed
- test_income_within_distribution_range

**tests/test_inventory.py:**
- test_add_and_retrieve_listing
- test_price_reduction_schedule — DOM triggers reductions
- test_listing_expiry — after 90 days
- test_mark_sold_removes_from_active
- test_market_stats_computed

**tests/test_clock.py:**
- test_date_advances_weekly
- test_season_detection
- test_peak_season

**tests/test_models.py:**
- test_property_creation
- test_listing_current_asking_after_reduction
- test_agent_equity_calculation
- test_agent_status_transitions

## Constraints

- Python 3.9 compatible
- numpy Generator API (no bare random)
- Pydantic v2 (model_dump() not .dict())
- All tests must pass
- No LLMs in any logic
- Deterministic given seed
- Canadian mortgage rules (semi-annual compounding, stress test, CMHC)
- All amounts in CAD
- Every module has a module-level docstring explaining its purpose

## Output

When done:
1. List all files created
2. Run `pytest -v` and show full output
3. Run a quick smoke test: generate 100 agents with seed=42, print summary stats (income distribution, max purchase price distribution, household type counts)
4. Git add + commit: "feat: Phase 1 — foundation models, financial math, agent generator, time engine"
