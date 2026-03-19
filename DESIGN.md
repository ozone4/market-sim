# Market Simulation Engine — Design Document

## Vision

A multi-agent market simulation that models realistic real estate market dynamics for a
municipality or neighbourhood. Thousands of demographically accurate buyer agents interact
with a live inventory of properties over simulated time. Market pressure, bidding wars,
and stale listings emerge naturally from the interaction of agent constraints and property
characteristics — not from hand-tuned formulas.

The primary use case is **assessment validation**: by simulating the market that existed
(or would exist) on a valuation date, we can identify properties whose assessed values
diverge from simulated market clearing behaviour.

## Core Principles

1. **Emergence over formula.** Bidding wars happen because many constrained agents compete
   for few affordable properties — not because we set `bid_multiplier = 1.05`.

2. **Financial realism first.** Every agent has income, savings, debt, mortgage
   pre-approval. Can they actually buy this property at this rate? That's the gate.
   Preferences are secondary to affordability.

3. **Deterministic and auditable.** Seed-based reproducibility. Every agent decision is
   loggable. No LLMs in the simulation loop.

4. **Time is a dimension.** The simulation runs week-by-week. Agents enter the market,
   search, bid, lose, adjust expectations, try again. Properties accumulate days-on-market.
   Price reductions happen. Urgency builds. This temporal dynamic is where the interesting
   signals emerge.

5. **Data-driven, not opinion-driven.** Agent demographics from census data. Income
   distributions from StatsCan. Interest rates from Bank of Canada. Property data from
   BC Assessment rolls. We parameterize from reality, not from guesses.

---

## Architecture

```
market-sim/
├── sim/
│   ├── __init__.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── generator.py       # Create agents from demographic distributions
│   │   ├── financial.py       # Mortgage math, affordability, GDS/TDS
│   │   ├── preferences.py     # What they want vs what they can afford
│   │   └── strategy.py        # Search → shortlist → bid → wait → retry
│   ├── market/
│   │   ├── __init__.py
│   │   ├── inventory.py       # Active listings, new entries, delistings, expirations
│   │   ├── clock.py           # Week-by-week simulation time engine
│   │   ├── transactions.py    # Completed sales log with full provenance
│   │   └── shocks.py          # Macro events: rate changes, recession, policy shifts
│   ├── properties/
│   │   ├── __init__.py
│   │   ├── models.py          # Property data model (from BC Assessment schema)
│   │   ├── loader.py          # Ingest from JSON/CSV/Assessment roll
│   │   ├── features.py        # Derived scores: view, transit, schools, walkability
│   │   └── pricing.py         # Asking price logic, price reductions over time
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── simulation.py      # Main loop: for each tick, agents act on market
│   │   ├── matching.py        # Which agents see which properties (search radius, filters)
│   │   └── auction.py         # Offer mechanics: single offer, multiple offer, bidding war
│   └── analysis/
│       ├── __init__.py
│       ├── assessment_gap.py  # Compare sim clearing prices to assessed values
│       ├── neighbourhood.py   # Aggregate neighbourhood-level signals
│       └── report.py          # Generate analysis reports
├── api/
│   ├── __init__.py
│   └── routes.py              # FastAPI endpoints
├── data/
│   ├── census/                # Income distributions, household demographics
│   ├── properties/            # Sample + real property data
│   └── rates/                 # Interest rate scenarios
├── tests/
├── docs/
├── DESIGN.md                  # This file
├── README.md
└── pyproject.toml
```

---

## Agent Model

### Demographics (from census data)

Each agent represents a household, not a person. Demographics determine financial
capacity and preferences.

| Attribute | Source | Effect |
|-----------|--------|--------|
| `household_type` | Census (couple no kids, couple w/ kids, single, retired, multi-gen) | Bedroom needs, property type preference |
| `annual_income` | StatsCan income distribution by region | Mortgage qualification |
| `savings` | Derived from income quintile + age bracket | Down payment capacity |
| `existing_debts` | Estimated from household type + income | TDS calculation |
| `age_bracket` | Census age distribution | Life stage → buyer archetype |
| `current_tenure` | Census (renter vs owner) | First-time buyer vs move-up |
| `current_home_value` | For owners: estimated from neighbourhood + type | Available equity |

### Financial Qualification (pure math, no LLM)

```
max_mortgage = qualifying_income / 12 × (1 - TDS_ratio) × amortization_factor(rate, 25yr)
max_purchase = max_mortgage + down_payment
down_payment = savings + (current_home_equity × 0.85)  # 85% of equity after selling costs

GDS check: (mortgage_payment + tax + heat) / gross_monthly_income ≤ 0.32
TDS check: (GDS_obligations + other_debts) / gross_monthly_income ≤ 0.40
Stress test: qualify at max(contract_rate + 2%, 5.25%)
```

This is the single most important gate. An agent who can't qualify simply doesn't bid.
No utility score overrides this — it's a hard constraint.

### Preferences (what they want, given what they can afford)

After filtering to affordable properties, agents rank by preference alignment:

| Factor | How scored | Weight varies by |
|--------|-----------|------------------|
| Location desirability | Neighbourhood score (0-10) from assessment data | Household type (families weight schools, retirees weight quiet) |
| Size fit | Floor area vs need (based on household size) | Household type |
| Condition tolerance | Building age + condition rating | Risk tolerance (young investor vs retiree) |
| Commute | Distance to employment centres | Working-age vs retired |
| Features | View, waterfront, suite, garage | Investor (suite=income), family (garage, yard) |
| Price relative to budget | How much of their max are they using? | Universal — everyone prefers paying less |

**Critical distinction:** Preferences determine which affordable property an agent prefers.
Financial qualification determines which properties are affordable. The old model mixed
these up — an agent with high "location_weight" could prefer a property they couldn't
actually buy.

### Strategy (temporal behaviour)

Each agent has a lifecycle in the simulation:

```
ENTERING → SEARCHING → SHORTLISTING → BIDDING → [WON | LOST]
                                                      ↓
                                               SEARCHING (again)
                                                      ↓
                                           (after N losses or M weeks)
                                               ADJUSTING
                                           (expand search, raise max price,
                                            consider different areas/types)
                                                      ↓
                                               SEARCHING (again)
                                                      ↓
                                           (after exhausting patience)
                                               EXITING
                                           (leaves market — rents, waits)
```

**Key temporal variables:**
- `weeks_in_market` — how long they've been looking (urgency increases)
- `losses` — number of lost bids (frustration → adjust expectations or exit)
- `patience` — weeks before exiting (varies by urgency: 8-52 weeks)
- `adjustment_threshold` — losses before expanding search criteria

---

## Property Model

### From BC Assessment Roll

| Field | Type | Notes |
|-------|------|-------|
| `folio_id` | str | Unique BC Assessment identifier |
| `assessed_value` | float | Current assessed value (what we're validating) |
| `property_type` | enum | SFD, townhouse, condo, duplex, manufactured |
| `bedrooms` | int | |
| `bathrooms` | float | |
| `floor_area` | float | sq ft |
| `lot_size` | float | sq ft |
| `year_built` | int | |
| `condition` | enum | poor/fair/average/good/excellent |
| `neighbourhood` | str | Assessment neighbourhood code |
| `location_score` | float | Derived from features.py |
| `features` | Features | View, waterfront, suite, garage, corner lot, etc. |

### Listing Dynamics

Properties don't just exist statically — they enter and leave the market:

```python
class Listing:
    property: Property
    asking_price: float          # Initially some function of assessed_value
    listed_date: SimDate         # When it entered the market
    days_on_market: int          # Tracked per tick
    price_reductions: list[PriceReduction]  # History of drops
    status: ListingStatus        # ACTIVE, PENDING, SOLD, EXPIRED, WITHDRAWN
    offers_received: int         # Count (public in some markets)
    
    # Asking price strategy
    initial_markup: float        # % above assessed value (varies by market heat)
    reduction_schedule: list     # e.g., drop 3% after 30 days, 5% after 60
```

**Asking price logic:**
- In hot markets: ask 5-15% above assessed value
- In balanced markets: ask 0-5% above assessed value  
- In cold markets: ask at or slightly below assessed value
- Price reductions: if no offers after N days, reduce by X%
- This creates the natural signal — overpriced listings accumulate DOM, eventually
  reduce, while underpriced listings generate immediate competition

---

## Market Engine

### Time Loop

```
for each week in simulation_period:
    1. Apply any macro shocks (rate change, policy, seasonal adjustment)
    2. Enter new listings (from listing schedule or stochastic model)
    3. Enter new buyers (from demographic pipeline)
    4. For each active agent:
       a. Search available inventory (filtered by affordability + geography)
       b. Rank affordable properties by preference
       c. Decide: bid on top choice, wait for more listings, or adjust criteria
    5. Resolve offers:
       a. Properties with single offer → negotiate (accept/counter/reject)
       b. Properties with multiple offers → bidding war
       c. Record transactions
    6. Update market state:
       a. Increment days-on-market for unsold listings
       b. Apply price reductions for stale listings
       c. Remove expired listings
       d. Update market temperature metrics
    7. Log everything
```

### Offer Resolution

**Single offer:** Accept if offer ≥ 95% of asking price (configurable by market heat).
Counter-offer if 90-95%. Reject if < 90%.

**Multiple offers (bidding war):**
```
Round 1: All interested agents submit initial offers
         (budget-constrained, preference-weighted)
Round 2-N: Agents see "there are N other offers" (not amounts)
           Decide to escalate, hold, or withdraw based on:
           - How much room they have (max_budget - current_offer)
           - Urgency (weeks_in_market, losses)
           - Risk tolerance
           Continue until one agent remains or all withdraw
```

**This is where emergence happens.** A property listed at $650K assessed value with an
asking price of $680K in a market where 12 buyers can afford it and only 3 alternatives
exist will naturally attract 4-5 offers and clear at $720-740K. We didn't program that
outcome — it arose from the constraint interactions.

### Macro Shocks

```python
class MacroShock:
    week: int                    # When the shock occurs
    shock_type: ShockType        # RATE_CHANGE, RECESSION, INVENTORY_SURGE, POLICY
    
    # Rate change
    new_rate: float              # e.g., 5.5% → 6.0%
    # Effect: requalify all agents, some drop out, max prices shrink
    
    # Recession
    income_impact: float         # e.g., -0.05 (5% income reduction for affected agents)
    affected_pct: float          # e.g., 0.15 (15% of agents affected)
    # Effect: some agents exit, others reduce budgets
    
    # Inventory surge
    new_listings: int            # Additional properties entering market
    # Effect: more choice → less competition → clearing prices drop
    
    # Policy (e.g., foreign buyer ban, first-time buyer incentive)
    agent_filter: Callable       # Which agents affected
    effect: Callable             # What changes
```

---

## Assessment Validation (the actual output)

After the simulation runs, every property that transacted has a simulated clearing price.
Compare to assessed value:

```python
class AssessmentSignal:
    folio_id: str
    assessed_value: float
    simulated_clearing_price: float     # Median across runs where this property sold
    clearing_range: ClearingRange       # p10/p50/p90
    assessment_gap_pct: float           # (clearing - assessed) / assessed
    num_offers_received: float          # Average across runs
    avg_days_on_market: float           # Average across runs
    times_sold: int                     # Out of N runs, how often did it sell?
    times_expired: int                  # How often did it fail to sell?
    competing_buyers: float             # Avg agents who could afford + were interested
    signal: AssessmentGapSignal         # under/over/within
    confidence: SignalConfidence        # Based on consistency across runs
```

**The key insight:** Properties that consistently generate bidding wars across runs (high
offers, low DOM, high sell rate) at prices above their assessed value → likely
under-assessed. Properties that consistently sit, get price reductions, and sell below
assessed value (or expire) → likely over-assessed. This signal is **emergent**, not
calculated from a formula.

---

## Data Requirements

### Minimum Viable (what we build with now)

- **25-50 sample properties** in a single neighbourhood (hand-crafted JSON, similar to
  current sample_properties.json but richer)
- **Agent demographics** from published StatsCan tables for Greater Victoria CMA
  (median income ~$95K, distribution shape)
- **Current interest rate** from Bank of Canada (posted 5-year fixed: ~5.0%)
- **Basic neighbourhood scores** (reuse from old model, good enough for MVP)

### Production Quality (when BC Assessment data available)

- **Full assessment roll** for a municipality (all folios with attributes)
- **Historical sales data** (for calibration — did the sim predict actual sale prices?)
- **Census microdata** for the specific area
- **MLS listing data** (asking prices, DOM, price changes — harder to get)

---

## What We Reuse from re-simulation

| Component | Reuse? | Notes |
|-----------|--------|-------|
| `Property` model | Adapt | Need more fields (bathrooms, DOM, listing status) |
| `BuyerArchetype` enum | Evolve | Replace with census-based household types |
| Neighbourhood scores | Copy | Good starting point |
| `BiddingResult` model | Adapt | Multi-round auction logic is sound |
| Calibration pipeline | Adapt | MAPE/bias/coverage metrics still apply |
| Batch processing | Adapt | Need batch-over-time, not batch-over-properties |
| FastAPI structure | Copy | Same API pattern |
| Test patterns | Copy | Same pytest structure |

---

## Phase Plan

### Phase 1: Foundation (this session)
- Project scaffolding, models, financial math
- Agent generator with census-based demographics
- Property model with listing dynamics
- Week-by-week time engine (no bidding yet — just agents entering/exiting, properties listing/expiring)
- Tests for all financial calculations

### Phase 2: Market Mechanics
- Search and matching (agents find affordable properties)
- Offer submission and resolution
- Bidding war mechanics
- Transaction recording
- Days-on-market tracking and price reductions

### Phase 3: Emergence Validation
- Run full simulation with sample data
- Verify that bidding wars emerge naturally on underpriced properties
- Verify that overpriced properties accumulate DOM
- Sensitivity analysis on financial parameters (rates, income distribution)
- Convergence testing

### Phase 4: Assessment Integration
- Assessment gap analysis from simulation output
- Neighbourhood aggregation
- Calibration against historical sales (when data available)
- API endpoints
- Reports

### Phase 5: Scale & Polish
- Multi-neighbourhood support
- Macro shock scenarios
- Visualization dashboard
- Performance optimization for large agent pools
- Documentation

---

## Non-Goals (for now)

- LLM-powered agent reasoning (maybe later for narrative reports)
- Real-time MLS data integration
- Rental market simulation
- Commercial property
- Land speculation / pre-development
- Cross-regional migration patterns

---

## Success Criteria

The model is useful if:

1. **Properties with known sale prices above assessed value** consistently generate
   bidding wars in simulation (true positive for under-assessment)
2. **Properties with known sale prices below assessed value** consistently sit in
   simulation (true positive for over-assessment)
3. **Changing interest rates** produces realistic affordability shifts (fewer qualified
   buyers at higher rates)
4. **Changing inventory** produces realistic competition shifts (more listings → less
   competition → lower clearing prices)
5. **Results are consistent across runs** with the same seed
6. **The assessment gap signal is not dominated by a single tuning parameter** (unlike
   the old model where bid_multiplier controlled everything)

That last one is the real test. If emergence works, the output should be robust to
reasonable parameter variation because it arises from structural interactions, not
from any single knob.
