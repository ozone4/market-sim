# market-sim

A multi-agent real estate market simulation engine for BC Assessment validation.

The system generates demographically realistic buyer agents that compete for properties over a configurable time horizon. Emergent market signals — bidding wars, price reductions, days-on-market accumulation — are compared against BC Assessment values to identify properties that may warrant reassessment review.

> **Disclaimer:** Results are indicators for assessment review prioritization only, not appraisal conclusions or market value determinations. All amounts in CAD.

---

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Quick smoke test
python scripts/cli.py smoke
```

---

## CLI Usage

```bash
# Single-run assessment gap analysis
python scripts/cli.py analyze --data data/properties/sample_victoria.json

# Write JSON + text report to a directory
python scripts/cli.py analyze --data data/properties/sample_victoria.json --output results/

# Multi-seed stability analysis
python scripts/cli.py analyze --data data/properties/sample_victoria.json --stable --runs 10

# Scenario comparison
python scripts/cli.py compare \
    --data data/properties/sample_victoria.json \
    --scenarios baseline_2024,rate_cut_cycle,recession

# List available scenarios
python scripts/cli.py scenarios
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--agents N` | 500 | Number of buyer agents |
| `--weeks N` | 26 | Simulation duration in weeks |
| `--rate R` | 0.05 | Mortgage contract rate |
| `--seed S` | 42 | Random seed |
| `--stable` | off | Run multi-seed stability analysis |
| `--runs N` | 10 | Seeds for `--stable` |
| `--output DIR` | — | Write reports to directory |

---

## API Endpoints

Start the API server:

```bash
uvicorn api.main:app --reload
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Liveness check |
| `POST` | `/api/analyze` | Single-run gap analysis |
| `POST` | `/api/analyze/stable` | Multi-run stability analysis |
| `POST` | `/api/analyze/scenario` | Run a named scenario |
| `POST` | `/api/analyze/compare` | Compare multiple scenarios |
| `POST` | `/api/simulate` | Raw simulation output |

### Example: Scenario analysis

```bash
curl -X POST http://localhost:8000/api/analyze/scenario \
  -H "Content-Type: application/json" \
  -d '{
    "properties": [...],
    "scenario": "rate_cut_cycle",
    "config": {"num_agents": 500, "num_weeks": 26}
  }'
```

### Example: Comparative analysis

```bash
curl -X POST http://localhost:8000/api/analyze/compare \
  -H "Content-Type: application/json" \
  -d '{
    "properties": [...],
    "scenarios": ["baseline_2024", "rate_cut_cycle", "recession"]
  }'
```

See [docs/API.md](docs/API.md) for full request/response schemas.

---

## Predefined Scenarios

| Key | Name | Description |
|-----|------|-------------|
| `baseline_2024` | Baseline 2024 | 5.0% rate, balanced market, no shocks |
| `rate_cut_cycle` | Rate Cut Cycle | BoC easing: 3 cuts of 25bp at weeks 4, 12, 20 |
| `rate_hike_stress` | Rate Hike Stress Test | Emergency hikes: +100bp at week 4, +50bp at week 12 |
| `recession` | Recession Scenario | 15% income reduction for 20% of agents + rate cut response |
| `inventory_surge` | Inventory Surge | High replenishment rate, surge shock at week 6 |
| `hot_market` | Hot Market | 3.5% rate, 800 agents, tight supply — bidding wars expected |

---

## Architecture Overview

```
sim/
├── agents/          # BuyerAgent generation, financial qualification, strategy
│   ├── financial.py # OSFI B-20 (GDS/TDS/stress test), CMHC premiums
│   ├── generator.py # Census-based demographic pools
│   ├── models.py    # BuyerAgent, FinancialProfile, PreferenceProfile
│   ├── preferences.py # PropertyScore (0-100 scale)
│   └── strategy.py  # Weekly action selection, bid amount calculation
├── engine/          # Simulation loop, matching, auction resolution
│   ├── simulation.py # run_simulation(), SimulationConfig, SimulationResult
│   ├── matching.py  # find_matches() — affordability + preference filtering
│   ├── auction.py   # resolve_offers() — single/multi-offer auction mechanics
│   └── context.py   # MarketContext (temperature, rate, seasonality)
├── market/          # Time engine, inventory, macro shocks
│   ├── clock.py     # SimulationClock — weekly ticks, seasons
│   ├── inventory.py # MarketInventory — DOM, price reductions, expiry
│   └── shocks.py    # MacroShock — rate changes, recessions, inventory surges
├── properties/      # Property models and JSON loader
├── analysis/        # Assessment gap analysis, neighbourhood aggregation
│   ├── assessment_gap.py   # Per-property gap signal (±8% threshold)
│   ├── neighbourhood.py    # Systemic signal aggregation
│   ├── stability.py        # Multi-run signal consistency
│   ├── comparative.py      # Cross-scenario comparison
│   └── report.py           # AnalysisReport generator
└── scenarios/       # Predefined macro-economic scenario presets
    └── presets.py   # SCENARIOS dict, apply_scenario()

api/                 # FastAPI application (6 endpoints)
scripts/
├── cli.py                  # Command-line interface (argparse)
├── generate_sample_data.py # Deterministic 220-property dataset generator
└── run_smoke_test.py       # Manual smoke test runner
data/
└── properties/
    ├── sample_victoria.json      # 30 sample Victoria properties
    └── sample_victoria_200.json  # 220 properties across 6 neighbourhoods
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system design.

---

## Sample Data

Two property datasets are included:

- **`sample_victoria.json`** — 30 curated properties across Oak Bay, Saanich East, Langford, View Royal with deliberate under/over/at-market test cases.
- **`sample_victoria_200.json`** — 220 properties across 6 neighbourhoods (Oak Bay, Saanich East, Langford, View Royal, Esquimalt, Colwood) with 5 under-assessed, 5 over-assessed, and 10 at-market deliberate test cases.

Regenerate the large dataset:

```bash
python scripts/generate_sample_data.py
```

---

## Running Tests

```bash
# Full suite
python -m pytest tests/ -v

# Phase-specific
python -m pytest tests/test_phase4.py -v

# Fast (skip slow performance tests)
python -m pytest tests/ -v -k "not performance"
```

**Current status:** 187 tests passing across 8 test files.

---

## Key Design Principles

1. **Emergence over formula** — bidding wars arise from constrained agents competing, not from hand-tuned multipliers.
2. **Financial realism** — OSFI B-20 qualification math (GDS/TDS/stress test, CMHC premiums, semi-annual compounding) drives affordability.
3. **Deterministic** — seed-based RNG; identical inputs produce identical results.
4. **Time is a dimension** — week-by-week dynamics; DOM accumulates; price reductions trigger; agents enter, search, bid, lose, adjust, exit.
5. **No LLMs** in the simulation or analysis pipeline.
6. **Regulatory disclaimer** — all output schemas include a `disclaimer` field per spec.
