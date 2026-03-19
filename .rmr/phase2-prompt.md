# Phase 2 — Market Mechanics: Search, Matching, Bidding Wars, Transactions

You are building Phase 2 of a multi-agent real estate market simulation at ~/Projects/market-sim/

**Read DESIGN.md first**, then read ALL existing code:
```
cat sim/agents/models.py
cat sim/agents/financial.py
cat sim/agents/generator.py
cat sim/properties/models.py
cat sim/properties/loader.py
cat sim/market/inventory.py
cat sim/market/clock.py
cat sim/market/shocks.py
cat data/properties/sample_victoria.json
```

## Purpose

Phase 1 built the pieces: agents with financial constraints, properties with listing dynamics, a time engine. Phase 2 makes them **interact**. Agents search the market, compare properties, submit offers, compete in bidding wars, and transact. This is where emergent behavior appears — or doesn't.

## What to build

### 1. Agent Preferences Scoring — `sim/agents/preferences.py`

Agents need to evaluate "how much do I like this property, given what I can afford?"

```python
def score_property(agent: BuyerAgent, listing: Listing, market_context: MarketContext) -> PropertyScore:
    """
    Score a property from this agent's perspective.
    
    Returns a score 0-100 where:
    - 0 = doesn't meet hard constraints (can't afford, wrong type, too few beds)
    - 1-30 = meets constraints but poor fit
    - 31-60 = acceptable
    - 61-80 = good fit
    - 81-100 = ideal match
    
    The score combines:
    1. Affordability comfort (how much of their max are they using? Less = more comfortable)
    2. Size fit (bedrooms vs need, floor area relative to household size)
    3. Type match (is this their preferred property type?)
    4. Location desirability (neighbourhood score, walkability, transit)
    5. Condition tolerance (newer/renovated scores higher for risk-averse agents)
    6. Feature bonuses (view, suite for investors, garage for families)
    
    Weights vary by household type — families weight bedrooms/schools more,
    investors weight suite/ROI potential, retirees weight condition/walkability.
    """
```

Key design decisions:
- Hard filter first: `qualifies_for_property()` and bedroom/type checks. If fail → score 0.
- Soft scoring on remaining factors, weighted by household type.
- `affordability_comfort` = 1 - (asking_price / max_price). Agents prefer to stay under budget.
- Return both the score AND a breakdown dict for auditability.

```python
@dataclass
class PropertyScore:
    total: float              # 0-100
    affordable: bool
    affordability_comfort: float  # 0-1, higher = more budget room
    size_fit: float           # 0-1
    type_match: float         # 0-1
    location_score: float     # 0-1  
    condition_score: float    # 0-1
    feature_bonus: float      # 0-1
    breakdown: dict           # Full scoring details for audit
```

Define HOUSEHOLD_SCORING_WEIGHTS — a dict mapping HouseholdType to weight vectors:

```python
HOUSEHOLD_SCORING_WEIGHTS = {
    HouseholdType.COUPLE_WITH_KIDS: {
        "affordability": 0.25,
        "size_fit": 0.25,
        "type_match": 0.10,
        "location": 0.20,  # Schools, parks
        "condition": 0.10,
        "features": 0.10,
    },
    HouseholdType.INVESTOR: {
        "affordability": 0.30,
        "size_fit": 0.05,
        "type_match": 0.10,
        "location": 0.15,
        "condition": 0.10,
        "features": 0.30,  # Suite = rental income!
    },
    HouseholdType.RETIREE: {
        "affordability": 0.20,
        "size_fit": 0.10,
        "type_match": 0.15,
        "location": 0.25,  # Walkability, transit
        "condition": 0.20,
        "features": 0.10,
    },
    # ... fill in ALL 8 household types
}
```

### 2. Market Context — `sim/engine/context.py`

A snapshot of market conditions that agents reference when making decisions.

```python
@dataclass
class MarketContext:
    current_week: int
    contract_rate: float
    avg_days_on_market: float
    active_listing_count: int
    recent_sale_count: int          # Sales in last 4 weeks
    avg_sale_to_asking_ratio: float # Recent sales: sale_price / asking_price
    season: str
    is_peak_season: bool
    
    @property
    def market_temperature(self) -> str:
        """hot / balanced / cold based on sale-to-ask ratio and DOM."""
        if self.avg_sale_to_asking_ratio > 1.02 and self.avg_days_on_market < 21:
            return "hot"
        elif self.avg_sale_to_asking_ratio < 0.97 or self.avg_days_on_market > 45:
            return "cold"
        return "balanced"
```

### 3. Search and Matching — `sim/engine/matching.py`

Each week, active agents search the market:

```python
def find_matches(
    agent: BuyerAgent,
    listings: list[Listing],
    market_context: MarketContext,
    max_results: int = 10,
) -> list[tuple[Listing, PropertyScore]]:
    """
    Find and rank properties this agent would consider.
    
    Steps:
    1. Filter by hard constraints (affordability, bedrooms, type)
    2. Score remaining properties
    3. Sort by score descending
    4. Return top max_results
    
    An agent in ADJUSTING status has relaxed constraints:
    - min_bedrooms reduced by 1
    - preferred_property_types expanded (add types adjacent to their preference)
    - max_price stretched by max_bid_stretch %
    """
```

### 4. Agent Strategy — `sim/agents/strategy.py`

The decision engine for each agent each week:

```python
def agent_weekly_action(
    agent: BuyerAgent,
    matches: list[tuple[Listing, PropertyScore]],
    market_context: MarketContext,
    rng: np.random.Generator,
) -> AgentAction:
    """
    Determine what an agent does this week.
    
    Returns an AgentAction (one of):
    - WAIT: not enough good options, or patience says wait for more listings
    - BID: submit an offer on their top-ranked property
    - ADJUST: expand search criteria (after enough losses)
    - EXIT: leave the market (patience exhausted)
    
    Decision logic:
    
    1. If weeks_in_market > patience_weeks → EXIT
    2. If bid_losses >= adjustment_threshold AND not already adjusted → ADJUST
    3. If no matches with score > 40 → WAIT
    4. If top match score > 60 OR (urgency > 0.7 AND top score > 40) → BID
    5. Else → WAIT (with probability based on remaining patience)
    """

class AgentAction:
    action_type: ActionType  # WAIT, BID, ADJUST, EXIT
    target_folio_id: Optional[str] = None  # For BID
    bid_amount: Optional[float] = None     # For BID
    reason: str = ""                       # Audit trail
```

**Bid amount calculation:**

```python
def calculate_bid_amount(
    agent: BuyerAgent,
    listing: Listing,
    score: PropertyScore,
    market_context: MarketContext,
    competing_offers: int,  # Number of known competing offers (may be 0 or estimated)
    rng: np.random.Generator,
) -> float:
    """
    How much does this agent bid?
    
    Base bid = current_asking_price (agents anchor on asking price)
    
    Adjustments:
    - Affordability comfort: if lots of budget room, willing to bid higher
    - Urgency: high urgency → stretch more
    - Competition: knowing there are competing offers → escalate
    - Market temperature: hot → bid higher, cold → bid lower/at asking
    - Score: higher property score → willing to stretch more for this one
    - Risk tolerance: high risk → stretch further
    
    Hard ceiling: max_price * (1 + max_bid_stretch)
    
    The bid should feel natural:
    - In a cold market with no competition: 95-100% of asking
    - In a balanced market: 97-103% of asking  
    - In a hot market with competition: 100-110% of asking
    - An urgent buyer who's lost 3 bids and loves the property: up to 115% of asking
    
    Add random noise (±1-2%) so identical agents don't all bid the same amount.
    """
```

### 5. Auction Mechanics — `sim/engine/auction.py`

Resolve offers on each property each week:

```python
@dataclass
class Offer:
    agent_id: str
    folio_id: str
    amount: float
    week: int
    is_escalation: bool = False
    round_number: int = 1

@dataclass  
class AuctionResult:
    folio_id: str
    outcome: AuctionOutcome  # SOLD, NO_OFFERS, REJECTED, PENDING
    winning_offer: Optional[Offer] = None
    all_offers: list[Offer] = field(default_factory=list)
    rounds: int = 1
    final_price: Optional[float] = None

def resolve_offers(
    folio_id: str,
    offers: list[Offer],
    listing: Listing,
    agents: dict[str, BuyerAgent],
    market_context: MarketContext,
    rng: np.random.Generator,
    max_rounds: int = 3,
) -> AuctionResult:
    """
    Resolve all offers on a property for this week.
    
    Scenarios:
    
    1. NO OFFERS → AuctionOutcome.NO_OFFERS (property sits)
    
    2. SINGLE OFFER:
       - If offer >= 95% of asking (balanced/cold) or >= 98% (hot) → SOLD
       - If offer >= 90% of asking → counter at asking price
         Agent accepts counter if urgency > 0.5 or score > 70
       - If offer < 90% → REJECTED
    
    3. MULTIPLE OFFERS (bidding war):
       Round 1: All offers on table. If highest is >= asking → proceed to escalation.
       Round 2-N: 
         Each agent sees "N other offers" (not amounts — sealed bid).
         Each agent decides to escalate or withdraw:
         - escalate_probability = risk_tolerance * urgency * (budget_remaining / asking)
         - escalation amount = 1-3% above their previous bid (bounded by max)
         Continue until one agent remains or max_rounds reached.
       Winner: highest final bid.
       SOLD at winner's price.
       
    All losing agents get status = LOST_BID, bid_losses += 1.
    """
```

### 6. Main Simulation Engine — `sim/engine/simulation.py`

The orchestrator that ties everything together:

```python
@dataclass
class SimulationConfig:
    num_agents: int = 500
    num_weeks: int = 26           # ~6 months
    contract_rate: float = 0.05
    seed: int = 42
    
    # Listing config
    initial_markup: float = 0.03    # Asking price = assessed * (1 + markup)
    markup_variance: float = 0.05   # ± variance on markup
    
    # Agent entry pattern
    agent_entry_mode: str = "front_loaded"  # front_loaded | gradual | random
    # front_loaded: 70% enter week 0-2, 30% trickle in over remaining weeks
    # gradual: equal batches each week
    # random: Poisson process
    
    # Shocks
    shocks: list[MacroShock] = field(default_factory=list)

@dataclass 
class SimulationState:
    config: SimulationConfig
    clock: SimulationClock
    inventory: MarketInventory
    agents: dict[str, BuyerAgent]  # agent_id → agent
    market_context: MarketContext
    transaction_log: list[AuctionResult]
    weekly_snapshots: list[WeeklySnapshot]

@dataclass
class WeeklySnapshot:
    week: int
    active_listings: int
    active_buyers: int
    offers_this_week: int
    sales_this_week: int
    expirations_this_week: int
    avg_sale_price: float
    avg_days_on_market: float
    market_temperature: str

def run_simulation(
    properties: list[Property],
    config: SimulationConfig,
) -> SimulationResult:
    """
    Run the full multi-agent market simulation.
    
    Main loop (for each week):
    
    1. MACRO SHOCKS
       - Apply any shocks scheduled for this week
       - Rate change → requalify all agents (some may lose qualification)
       - Recession → reduce income for affected agents, some exit
       - Inventory surge → add new listings
    
    2. AGENT ENTRY
       - New agents enter per entry_mode schedule
    
    3. INVENTORY TICK
       - Increment DOM for active listings
       - Apply price reductions
       - Expire stale listings
    
    4. MATCHING
       - For each SEARCHING/ADJUSTING agent:
         - Find matching properties (affordability + preference filter)
         - If good matches found → submit offer on top choice
         - If no matches → WAIT or ADJUST or EXIT
    
    5. OFFER RESOLUTION
       - Group offers by property
       - Resolve each property's offers (single/multiple/bidding war)
       - Record transactions
       - Update winning agents → WON status
       - Update losing agents → LOST_BID, increment losses
    
    6. STATE UPDATE  
       - Update market context (DOM averages, sale-to-ask ratio, temperature)
       - Capture weekly snapshot
       - Transition agents who've exhausted patience → EXITED
       - Transition agents with enough losses → ADJUSTING
    
    7. LOG EVERYTHING
    
    After loop:
    - Compile SimulationResult with all transactions, agent outcomes, weekly snapshots
    """

@dataclass
class SimulationResult:
    config: SimulationConfig
    transactions: list[AuctionResult]  # All completed sales
    weekly_snapshots: list[WeeklySnapshot]
    agent_outcomes: dict[str, AgentOutcome]  # How each agent ended up
    properties_unsold: list[str]  # folio_ids that never sold
    properties_sold: list[str]
    total_weeks: int
    seed: int
    
@dataclass
class AgentOutcome:
    agent_id: str
    household_type: str
    final_status: str          # WON, EXITED, SEARCHING (still looking at sim end)
    property_purchased: Optional[str] = None
    purchase_price: Optional[float] = None
    weeks_to_purchase: Optional[int] = None
    bids_submitted: int = 0
    bids_lost: int = 0
```

### 7. Smoke Test Script — `scripts/run_smoke_test.py`

A standalone script that runs the simulation and prints human-readable results:

```python
"""
Smoke test: run simulation with sample Victoria data and 500 agents.
Print results to stdout for human review.

Usage: python scripts/run_smoke_test.py
"""
# Load 30 sample properties
# Generate 500 agents
# Run 26-week simulation
# Print:
#   - Weekly summary (listings, sales, DOM, temperature)
#   - Properties that sold: folio_id, assessed, asking, sale_price, DOM, num_offers
#   - Properties that didn't sell: folio_id, assessed, asking, DOM, why not?
#   - Agent outcomes: how many bought, how many exited, how many still looking
#   - The KEY output: for each property, assessed_value vs clearing_price — 
#     does the simulation identify the underpriced one? The overpriced one?
```

This is the most important output. If the simulation shows that the deliberately
underpriced property (check sample_victoria.json for which one it is) gets a bidding
war and sells above assessed, while the overpriced one sits or sells below assessed,
**emergence is working**.

### 8. Tests — `tests/test_phase2.py`

25+ tests:

**Scoring:**
- test_unaffordable_property_scores_zero
- test_wrong_type_scores_lower
- test_perfect_match_scores_high
- test_investor_weights_suite_heavily
- test_family_weights_bedrooms_heavily

**Matching:**
- test_finds_affordable_properties_only
- test_adjusting_agent_relaxes_constraints
- test_max_results_respected
- test_no_matches_returns_empty

**Strategy:**
- test_patient_agent_waits_with_low_scores
- test_urgent_agent_bids_on_mediocre_match
- test_exhausted_patience_exits
- test_losses_trigger_adjustment

**Bidding:**
- test_bid_within_budget
- test_bid_above_asking_in_hot_market
- test_bid_below_asking_in_cold_market
- test_bid_never_exceeds_max_with_stretch

**Auction:**
- test_single_offer_accepted
- test_single_low_offer_rejected
- test_multiple_offers_highest_wins
- test_bidding_war_escalation
- test_no_offers_returns_no_offers
- test_losing_agents_get_loss_count

**Engine:**
- test_simulation_runs_to_completion
- test_deterministic_with_seed
- test_rate_hike_reduces_buyers
- test_properties_accumulate_dom
- test_price_reductions_happen

## Constraints

- Python 3.9 compatible (use `from __future__ import annotations`)
- numpy Generator API throughout (no bare random)
- Pydantic v2 (model_dump() not .dict())
- All Phase 1 tests (93) must still pass
- New Phase 2 tests must pass
- Deterministic given seed
- Every module has a module-level docstring
- No LLMs anywhere in the logic
- All amounts in CAD

## Critical implementation note

The auction resolution MUST handle the case where an agent bids on a property, loses, and then needs to go back to SEARCHING next week. Don't leave agents stuck in BIDDING forever. Each week's cycle must cleanly resolve all pending offers.

## Output

When done:
1. List all files created/modified
2. Run `pytest -v` and show full output (must show 93 + new tests passing)
3. Run the smoke test script and show the full output
4. Git commit: "feat: Phase 2 — search, matching, bidding wars, auction mechanics, simulation engine"

THE SMOKE TEST OUTPUT IS THE MOST IMPORTANT THING. If the underpriced property gets a bidding war and the overpriced one sits — we've achieved emergence.
