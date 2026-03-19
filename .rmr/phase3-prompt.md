# Phase 3 — Assessment Integration, Analysis, and API

## Context

You are working on `~/Projects/market-sim/`, a multi-agent real estate market simulation engine for BC Assessment validation. Phases 1 and 2 are complete (122 tests passing). The simulation runs 500 demographically-sampled buyer agents across 26 weeks against property inventories, producing emergent bidding wars, price reductions, and market clearing behavior.

**What exists:**
- `sim/agents/` — financial.py (Canadian mortgage math), generator.py (census demographics), models.py (BuyerAgent, 8 HouseholdTypes), preferences.py (PropertyScore 0-100), strategy.py (weekly action + bid calculation)
- `sim/engine/` — simulation.py (SimulationConfig, run_simulation, SimulationResult), auction.py (single/multi-offer resolution), matching.py (find_matches), context.py (MarketContext)
- `sim/market/` — inventory.py (MarketInventory, DOM tracking, price reductions at 21/42/63 days, expiry at 90), clock.py (weekly ticks, seasons), shocks.py (MacroShock: rate changes, recession)
- `sim/properties/` — models.py (Property, Listing, Features, Location), loader.py (JSON ingestion)
- `sim/analysis/` — empty (just __init__.py)
- `data/properties/sample_victoria.json` — 30 properties ($320K–$2.1M, Oak Bay/Saanich East/Langford/View Royal)
- `scripts/run_smoke_test.py` — human-readable output
- `tests/` — 6 test files, 122 tests passing

**Known Phase 2 issues to address in this phase:**
1. Market clears too fast (30 properties sell by week 6, 20 empty weeks). Fix: add inventory replenishment option to SimulationConfig.
2. Budget-constrained agents dogpile cheapest properties (VR-003 got 89 offers). Fix: agent generator should produce wider income spread in middle brackets.

## What to Build

### 1. Assessment Gap Analysis (`sim/analysis/assessment_gap.py`)

Compare simulation clearing prices to BC Assessment values.

```python
@dataclass
class AssessmentGapResult:
    folio_id: str
    assessed_value: float
    simulated_clearing_price: float   # Final sale price from simulation
    gap_pct: float                     # (clearing - assessed) / assessed * 100
    gap_signal: str                    # "under_assessed" | "over_assessed" | "within_tolerance"
    confidence: str                    # "high" | "medium" | "low"
    market_pressure_score: float       # 0-10 scale
    days_on_market: int
    offer_count: int
    rounds: int
    review_recommendation: str         # "flag_for_review" | "within_norms" | "data_insufficient"
```

**Gap signal thresholds:**
- `|gap_pct| <= 8%` → within_tolerance
- `gap_pct > 8%` → under_assessed (market would pay significantly more)
- `gap_pct < -8%` → over_assessed (market wouldn't support the assessment)

**Confidence scoring:**
- `high`: ≥3 offers, DOM < 30, gap direction consistent across multiple seed runs
- `medium`: 1-2 offers, DOM 30-60
- `low`: 0 offers (expired), DOM > 60, or only sold due to price reductions

**Market pressure score (0-10):**
- Offers received: 0→0, 1→2, 2-3→4, 4-5→6, 6-10→8, >10→10
- DOM modifier: <14d → +1, 14-30d → 0, 30-60d → -1, >60d → -2
- Rounds modifier: 1→0, 2→+0.5, 3→+1
- Clamp to [0.0, 10.0]

**Review recommendation:**
- `flag_for_review`: |gap_pct| > 15% AND confidence != "low"
- `data_insufficient`: property expired unsold OR confidence == "low"
- `within_norms`: everything else

Functions:
```python
def analyze_property_gap(folio_id: str, result: SimulationResult, properties: dict[str, Property]) -> AssessmentGapResult
def analyze_all_gaps(result: SimulationResult, properties: list[Property]) -> list[AssessmentGapResult]
```

### 2. Neighbourhood Aggregation (`sim/analysis/neighbourhood.py`)

Roll up property-level signals to neighbourhood level.

```python
@dataclass
class NeighbourhoodSummary:
    neighbourhood: str
    municipality: str
    property_count: int
    avg_gap_pct: float
    median_gap_pct: float
    under_assessed_count: int
    over_assessed_count: int
    within_tolerance_count: int
    avg_market_pressure: float
    avg_dom: float
    systemic_signal: str              # "systemic_under" | "systemic_over" | "mixed" | "within_norms"
    flagged_for_review: int           # Count of properties recommended for review
```

**Systemic signal logic:**
- >60% of properties signal the same direction → systemic_under or systemic_over
- >30% each direction → mixed
- Otherwise → within_norms

Functions:
```python
def summarize_neighbourhood(neighbourhood: str, gap_results: list[AssessmentGapResult], properties: list[Property]) -> NeighbourhoodSummary
def summarize_all_neighbourhoods(gap_results: list[AssessmentGapResult], properties: list[Property]) -> list[NeighbourhoodSummary]
```

### 3. Multi-Run Stability Analysis (`sim/analysis/stability.py`)

Run the simulation N times with different seeds and measure how stable the signals are.

```python
@dataclass
class StabilityResult:
    folio_id: str
    num_runs: int
    clearing_prices: list[float]       # One per run
    gap_signals: list[str]             # One per run
    mean_clearing_price: float
    std_clearing_price: float
    p10_clearing_price: float
    p90_clearing_price: float
    dominant_signal: str               # Most common gap_signal
    signal_agreement_pct: float        # % of runs agreeing with dominant signal
    stability: str                     # "stable" (>80%), "moderate" (60-80%), "unstable" (<60%)
```

Functions:
```python
def run_stability_analysis(
    properties: list[Property],
    base_config: SimulationConfig,
    num_runs: int = 10,
    seed_offset: int = 1000,
) -> dict[str, StabilityResult]
```

Each run uses `seed = base_config.seed + seed_offset * run_index`. Reuse the existing `run_simulation()` — do NOT duplicate the engine.

### 4. Inventory Replenishment (fix Phase 2 Issue #1)

Add to `SimulationConfig`:
```python
replenishment_rate: float = 0.0    # 0.0 = no replenishment; 0.05 = 5% of initial inventory added per week
replenishment_variance: float = 0.02  # Jitter on per-week entry count
```

In `run_simulation()`, after agent entry (step 2), generate new listings:
- Each week, expected new listings = `len(properties) * replenishment_rate`
- Actual count drawn from Poisson(expected) with variance
- New properties are **clones of random existing properties** with:
  - New folio_id (original + `-R{week}`)
  - Assessed value jittered ±5%
  - Fresh asking price using the same markup logic
- This simulates similar properties entering the market over time

### 5. Income Spread Fix (fix Phase 2 Issue #2)

In `sim/agents/generator.py`, the income distribution needs wider spread in the $80K–$150K range. Currently the census weights likely cluster too tightly.

Adjust the income sampling so that:
- 15% of agents have income < $60K (observers — can only afford condos/manufactured)
- 30% have income $60K–$100K (starter homes, townhouses, Langford SFDs)
- 30% have income $100K–$160K (mid-range SFDs, Saanich East)
- 15% have income $160K–$250K (premium, Oak Bay lower)
- 10% have income > $250K (luxury, Oak Bay waterfront)

This should reduce the dogpiling effect on cheap properties and spread competition more evenly.

### 6. Report Generator (`sim/analysis/report.py`)

```python
@dataclass
class AnalysisReport:
    run_date: str                          # ISO date
    config_summary: dict                   # Serialized SimulationConfig
    property_results: list[AssessmentGapResult]
    neighbourhood_summaries: list[NeighbourhoodSummary]
    stability_results: Optional[dict[str, StabilityResult]]
    
    # Aggregate stats
    total_properties: int
    total_sold: int
    total_unsold: int
    flagged_for_review: int
    systemic_signals: list[str]            # Neighbourhoods with systemic signals
    
    disclaimer: str = (
        "This analysis is based on simulated market behavior using "
        "rule-based agent models. Results are indicators for assessment "
        "review prioritization, not appraisal conclusions or market "
        "value determinations. All amounts in CAD."
    )
```

Functions:
```python
def generate_report(
    result: SimulationResult,
    properties: list[Property],
    stability: Optional[dict[str, StabilityResult]] = None,
    config: Optional[SimulationConfig] = None,
) -> AnalysisReport
```

### 7. FastAPI Application (`api/routes.py`)

```python
# POST /api/analyze
# Body: { properties: [...], config: {...} }
# Returns: AnalysisReport (single-run, no stability)

# POST /api/analyze/stable
# Body: { properties: [...], config: {...}, num_runs: 10 }
# Returns: AnalysisReport WITH stability_results

# GET /api/health
# Returns: { status: "ok", version: "0.3.0", tests_passing: 122 }

# POST /api/simulate
# Body: SimulationConfig + properties
# Returns: Raw SimulationResult (for debugging/exploration)
```

Use Pydantic v2 models for request/response schemas. All response models must include a `disclaimer` field.

Create `api/schemas.py` for API-specific Pydantic models that wrap the internal dataclasses:
- `AnalyzeRequest`, `AnalyzeResponse`, `StableAnalyzeRequest`, `SimulateRequest`, `SimulateResponse`, `HealthResponse`

### 8. Documentation

Create `docs/` directory with:

**`docs/ARCHITECTURE.md`** — System overview, module map, data flow diagram (text-based)
**`docs/API.md`** — Endpoint documentation with example requests/responses
**`docs/METHODOLOGY.md`** — How the simulation works, what the signals mean, limitations
**`docs/CALIBRATION.md`** — How to tune parameters, what each config knob does

### 9. Tests (`tests/test_phase3.py`)

Write **at least 15 tests** covering:
1. `analyze_property_gap` — sold property → correct gap calculation
2. `analyze_property_gap` — unsold property → data_insufficient
3. `analyze_all_gaps` — returns results for all properties
4. Market pressure score calculation — boundary cases (0 offers, 10+ offers)
5. Gap signal thresholds — exactly at 8%, above, below
6. Confidence levels — high (many offers), medium, low (expired)
7. Review recommendation logic
8. `summarize_neighbourhood` — systemic_under signal (>60% under)
9. `summarize_neighbourhood` — mixed signal
10. `summarize_neighbourhood` — within_norms
11. `run_stability_analysis` — stable property (signal_agreement > 80%)
12. `run_stability_analysis` — deterministic (same seeds = same results)
13. Inventory replenishment — new listings appear in later weeks
14. Income spread — verify distribution buckets match spec
15. FastAPI health endpoint returns 200
16. FastAPI /api/analyze returns valid AnalysisReport

## Constraints

- **Python 3.9** compatible
- **numpy Generator API** (`np.random.default_rng`) — no bare `random.random()`
- **Pydantic v2** everywhere (`.model_dump()` not `.dict()`)
- **Deterministic** given seed — stability analysis must produce identical results across runs with same config
- **No LLMs** in any simulation or analysis logic
- **All monetary values in CAD**
- **No forbidden language**: Do not use "price prediction", "listing price", "today's market", "over asking" — we are analyzing assessment gaps, not predicting prices
- **All output schemas must include a disclaimer field**
- **Run the full test suite** (`pytest tests/ -v`) and ensure ALL tests pass (existing 122 + new 15+)

## Git

After all tests pass, commit:
```
feat: Phase 3 — assessment gap analysis, neighbourhood aggregation, stability analysis, API
```

Do NOT commit if tests fail. Fix first.
