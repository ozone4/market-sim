# Phase 4 — Scale, Scenarios, Visualization, and Polish

## Context

You are working on `~/Projects/market-sim/`, a multi-agent real estate market simulation engine for BC Assessment validation. Phases 1-3 are complete (156 tests passing). The system has:

- Agent generation (census demographics, Canadian mortgage math, 8 household types)
- Market simulation (weekly ticks, matching, bidding wars, price reductions, auctions)
- Assessment gap analysis (±8% thresholds, confidence, market pressure 0-10)
- Neighbourhood aggregation (systemic signals)
- Multi-run stability analysis (10+ seeds)
- Report generation
- FastAPI API (4 endpoints)
- Inventory replenishment
- 30 sample properties across Oak Bay, Saanich East, Langford, View Royal

**Activate the venv before running anything:** `source .venv/bin/activate`

## What to Build

### 1. Scenario Engine (`sim/scenarios/`)

Create predefined macro-economic scenarios that bundle shock schedules + config overrides.

**`sim/scenarios/presets.py`:**

```python
@dataclass
class Scenario:
    name: str
    description: str
    config_overrides: dict           # Override SimulationConfig fields
    shocks: list[MacroShock]         # Shock schedule for the scenario
    
SCENARIOS: dict[str, Scenario] = {
    "baseline_2024": Scenario(
        name="Baseline 2024",
        description="Current conditions: 5.0% rate, balanced market",
        config_overrides={"contract_rate": 0.05, "num_weeks": 26},
        shocks=[],
    ),
    "rate_cut_cycle": Scenario(
        name="Rate Cut Cycle",
        description="BoC easing: 3 cuts of 25bp at weeks 4, 12, 20",
        config_overrides={"contract_rate": 0.05},
        shocks=[
            MacroShock(week=4, shock_type="rate_cut", magnitude=-0.0025),
            MacroShock(week=12, shock_type="rate_cut", magnitude=-0.0025),
            MacroShock(week=20, shock_type="rate_cut", magnitude=-0.0025),
        ],
    ),
    "rate_hike_stress": Scenario(
        name="Rate Hike Stress Test",
        description="Emergency hikes: +100bp at week 4, +50bp at week 12",
        config_overrides={"contract_rate": 0.05},
        shocks=[
            MacroShock(week=4, shock_type="rate_hike", magnitude=0.01),
            MacroShock(week=12, shock_type="rate_hike", magnitude=0.005),
        ],
    ),
    "recession": Scenario(
        name="Recession Scenario",
        description="Economic downturn: recession shock + rate cut response",
        config_overrides={"contract_rate": 0.05, "num_weeks": 52},
        shocks=[
            MacroShock(week=8, shock_type="recession", magnitude=0.15),   # 15% income reduction
            MacroShock(week=16, shock_type="rate_cut", magnitude=-0.005),  # Policy response
            MacroShock(week=24, shock_type="rate_cut", magnitude=-0.005),
        ],
    ),
    "inventory_surge": Scenario(
        name="Inventory Surge",
        description="Sudden listing wave: 50% more inventory at week 6",
        config_overrides={"replenishment_rate": 0.08},
        shocks=[
            MacroShock(week=6, shock_type="inventory_surge", magnitude=0.5),
        ],
    ),
    "hot_market": Scenario(
        name="Hot Market",
        description="Low rates + tight supply: bidding wars expected",
        config_overrides={"contract_rate": 0.035, "num_agents": 800, "replenishment_rate": 0.02},
        shocks=[],
    ),
}
```

Add a new API endpoint: `POST /api/analyze/scenario` that accepts a scenario name + properties.

### 2. Comparative Analysis (`sim/analysis/comparative.py`)

Run two or more scenarios on the same properties and diff the results.

```python
@dataclass
class PropertyComparison:
    folio_id: str
    assessed_value: float
    scenarios: dict[str, float]          # scenario_name → clearing_price
    gap_signals: dict[str, str]          # scenario_name → gap_signal
    pressure_scores: dict[str, float]    # scenario_name → market_pressure_score
    most_sensitive_scenario: str         # Scenario where gap_pct changed most
    sensitivity_range_pct: float         # Max gap_pct - min gap_pct across scenarios

@dataclass
class ComparativeReport:
    scenarios_run: list[str]
    property_comparisons: list[PropertyComparison]
    neighbourhood_comparison: dict[str, dict[str, str]]  # neighbourhood → {scenario → systemic_signal}
    disclaimer: str = DISCLAIMER
```

Functions:
```python
def run_comparative_analysis(
    properties: list[Property],
    scenario_names: list[str],
    base_config: Optional[SimulationConfig] = None,
) -> ComparativeReport
```

API endpoint: `POST /api/analyze/compare` — body: `{ "properties": [...], "scenarios": ["baseline_2024", "rate_cut_cycle", "recession"] }`

### 3. CLI Runner (`scripts/cli.py`)

A proper CLI for running analyses from the command line.

```bash
# Single run with sample data
python scripts/cli.py analyze --data data/properties/sample_victoria.json --output results/

# Stability analysis
python scripts/cli.py analyze --data data/properties/sample_victoria.json --stable --runs 10

# Scenario comparison
python scripts/cli.py compare --data data/properties/sample_victoria.json --scenarios baseline_2024,rate_cut_cycle,recession

# Quick smoke test
python scripts/cli.py smoke

# List available scenarios
python scripts/cli.py scenarios
```

Use `argparse` (stdlib only — no click/typer dependency). Output to console by default, `--output DIR` writes JSON + text report.

The text report should be human-readable like the smoke test output. Include:
- Property-level gap analysis table
- Neighbourhood summary table  
- Flagged-for-review list
- Config summary

### 4. Performance Scaling (`sim/engine/simulation.py` enhancement)

The current simulation handles 500 agents × 30 properties in 0.2s. Ensure it scales:

- Add `SimulationConfig.max_matches_per_agent: int = 10` — cap how many properties each agent evaluates per week (prevents O(agents × listings) blowup)
- Pre-filter agents by max_purchase_price range before running full scoring (skip agents who can't afford the cheapest listing)
- Profile and optimize hot paths:
  - `find_matches()` should use a sorted-by-price index instead of scanning all listings per agent
  - `score_property()` should short-circuit on hard filters before computing soft scores (already does this — verify)

Target: 5,000 agents × 200 properties in < 5 seconds.

### 5. Enhanced Sample Data (`data/properties/sample_victoria_200.json`)

Generate a larger sample dataset: 200 properties across the same 4 neighbourhoods (Oak Bay, Saanich East, Langford, View Royal) plus 2 new ones (Esquimalt, Colwood).

Distribution:
- Oak Bay: 40 properties ($800K–$2.5M, mix of SFD/condo/townhouse)
- Saanich East: 50 properties ($500K–$1.4M)
- Langford: 45 properties ($400K–$1.0M, newer builds)
- View Royal: 30 properties ($450K–$1.1M)
- Esquimalt: 20 properties ($400K–$900K, older stock, more condos)
- Colwood: 15 properties ($450K–$950K, newer subdivisions)

Include deliberate test cases:
- 5 properties assessed 20%+ below market (clear under-assessment)
- 5 properties assessed 20%+ above market (clear over-assessment)
- 10 properties at market (within ±5%)

Write a `scripts/generate_sample_data.py` script that creates this deterministically (seed-based). The script should be re-runnable and produce identical output.

### 6. Expanded Tests (`tests/test_phase4.py`)

At least 15 new tests:
1. Scenario loading — all presets load without error
2. Scenario config overrides apply correctly
3. Rate cut scenario — agents can afford more (higher clearing prices)
4. Rate hike scenario — agents afford less (lower clearing prices or unsold)
5. Recession scenario — some properties go unsold
6. Comparative analysis — 2 scenarios produce different gap signals
7. Comparative analysis — sensitivity_range_pct is positive
8. CLI smoke command exits 0
9. CLI scenarios command lists all presets
10. Large dataset loads (200 properties)
11. Performance: 1000 agents × 100 properties < 3s
12. Performance: max_matches_per_agent reduces computation
13. Scenario API endpoint returns valid response
14. Compare API endpoint returns valid ComparativeReport
15. Text report output includes all sections

### 7. README Update

Update the project `README.md` with:
- Project description (assessment validation via multi-agent market simulation)
- Quick start (venv, install, run smoke test)
- CLI usage examples
- API endpoint summary
- Scenario descriptions
- Architecture overview (link to docs/)
- Test running instructions
- Disclaimer

## Constraints

- **Python 3.9** compatible
- **numpy Generator API** — no bare `random.random()`
- **Pydantic v2** (`.model_dump()` not `.dict()`)
- **Deterministic** given seed
- **No LLMs** in simulation or analysis
- **All monetary values in CAD**
- **No forbidden language**: "price prediction", "listing price", "today's market", "over asking"
- **All output schemas must include a disclaimer field**
- **Run the FULL test suite** (`python -m pytest tests/ -v`) and ensure ALL 156 existing + 15+ new tests pass
- **Do not break any existing tests** — run the full suite, not just new tests
- **argparse only** for CLI (no click/typer — keep dependencies minimal)

## Git

After all tests pass, commit:
```
feat: Phase 4 — scenarios, comparative analysis, CLI, performance, 200-property dataset
```

Do NOT commit if tests fail. Fix first.
