# Market Simulation Engine — Project Status

**Project:** BC Assessment Market Pressure Analysis Tool  
**Path:** `~/Projects/market-sim/`  
**Started:** March 18, 2026  
**Status:** v1 Complete — 187 tests passing  
**Runtime:** Python 3.9.6, numpy, FastAPI, Pydantic v2  

---

## What It Is

A multi-agent Monte Carlo simulation that models realistic buyer behaviour in the Greater Victoria real estate market. Instead of using formulas or regression to estimate property values, it generates thousands of demographically accurate buyer agents — each with real income, savings, debt, mortgage pre-approval — and lets them compete for properties over simulated weeks.

What emerges:
- **Underpriced properties** get swarmed with offers, bidding wars, and fast sales
- **Overpriced properties** sit, accumulate days-on-market, and take price reductions
- **Assessment gaps** become visible when simulated clearing prices diverge from BC Assessment values

The primary use case is **assessment validation**: identifying properties whose assessed values may warrant reassessment review, and detecting systemic under- or over-assessment at the neighbourhood level.

---

## Core Design Principles

1. **Emergence over formula** — Bidding wars happen because many constrained agents compete for few affordable properties, not because we set `bid_multiplier = 1.05`
2. **Financial realism first** — Canadian mortgage math (semi-annual compounding, OSFI B-20 stress test, CMHC insurance, GDS/TDS limits). Affordability gates preferences.
3. **Deterministic and auditable** — Seed-based reproducibility via numpy Generator API. Every agent decision is loggable. No LLMs in the simulation loop.
4. **Time is a dimension** — Week-by-week simulation. Agents enter, search, bid, lose, adjust expectations, try again. Properties accumulate DOM. Urgency builds.
5. **Data-driven** — Census demographics, StatsCan income distributions, Bank of Canada rates. Parameterized from reality.

---

## Architecture

```
market-sim/
├── sim/
│   ├── agents/
│   │   ├── financial.py      Canadian mortgage math (GDS/TDS, stress test, CMHC)
│   │   ├── generator.py      Census-derived agent pool (8 household types)
│   │   ├── models.py         BuyerAgent, FinancialProfile, BehaviorProfile
│   │   ├── preferences.py    PropertyScore (0-100), per-household-type weights
│   │   └── strategy.py       Weekly action selection, bid amount calculation
│   ├── engine/
│   │   ├── auction.py        Single-offer + multi-offer bidding war resolution
│   │   ├── context.py        MarketContext (temperature, seasonality, rate)
│   │   ├── matching.py       Affordability + preference filtering, sorted index
│   │   └── simulation.py     Main weekly loop, SimulationConfig, SimulationResult
│   ├── market/
│   │   ├── clock.py          Weekly ticks, season detection (peak: Mar-Jun)
│   │   ├── inventory.py      DOM tracking, price reductions (21/42/63d), expiry 90d
│   │   └── shocks.py         MacroShock: rate hike/cut, recession, inventory surge
│   ├── properties/
│   │   ├── loader.py         JSON ingestion with Pydantic v2 validation
│   │   └── models.py         Property, Listing, Location, Features
│   ├── analysis/
│   │   ├── assessment_gap.py Per-property gap signal vs BC Assessment
│   │   ├── neighbourhood.py  Neighbourhood-level systemic signal aggregation
│   │   ├── stability.py      Multi-seed consistency measurement
│   │   ├── comparative.py    Side-by-side scenario comparison
│   │   └── report.py         Full AnalysisReport generator
│   └── scenarios/
│       └── presets.py        6 macro-economic scenario bundles
├── api/
│   ├── main.py               FastAPI app
│   ├── routes.py             7 endpoints
│   └── schemas.py            Pydantic v2 request/response models
├── scripts/
│   ├── cli.py                CLI: analyze, compare, smoke, scenarios
│   ├── run_smoke_test.py     Human-readable simulation output
│   └── generate_sample_data.py  Deterministic 200-property generator
├── data/properties/
│   ├── sample_victoria.json        30 properties (4 neighbourhoods)
│   └── sample_victoria_200.json    220 properties (6 neighbourhoods)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── METHODOLOGY.md
│   └── CALIBRATION.md
├── tests/                    187 tests across 8 files
├── DESIGN.md                 Original design document
└── README.md                 Quick start + usage guide
```

**Total:** ~8,700 lines of Python across 42 files

---

## What Each Phase Built

### Phase 1 — Foundation (93 tests)
*Commit: `fd055c8`*

- **Canadian mortgage math** — Semi-annual compounding (Canadian standard), OSFI B-20 stress test (`max(contract+2%, 5.25%)`), CMHC insurance premiums, tiered minimum down payment, GDS/TDS limits (0.32/0.40)
- **Agent generator** — Census-derived demographics for Greater Victoria CMA. 8 household types (single young, couple no kids, couple with kids, single parent, retiree downsizer, investor, multi-generational, new immigrant). Income, savings, debt, equity, preferences all sampled from StatsCan distributions.
- **Property models** — Pydantic v2 models for Property, Listing, Features, Location. JSON loader with validation.
- **Market mechanics** — Inventory lifecycle (listing → active → sold/expired), DOM tracking, automatic price reductions at 21/42/63 days, expiry at 90 days. Weekly clock with season detection. Macro shocks (rate changes, recession, inventory surges).
- **Sample data** — 30 properties across Oak Bay, Saanich East, Langford, View Royal ($320K–$2.1M) with 3 deliberate test cases (underpriced, overpriced, average)

### Phase 2 — Market Mechanics (122 tests, +29 new)
*Commit: `659a487`*

- **Property scoring** — 0-100 composite score. Hard filters gate to 0 (can't afford it, wrong bedroom count, wrong property type). Soft factors weighted by household type (couple with kids weights size_fit 0.25 vs single_young at 0.10).
- **Strategy engine** — Weekly action selection (WAIT/BID/ADJUST/EXIT) based on urgency, fatigue, market context. Bid calculation anchored on asking price, adjusted for market temperature, property score, urgency, competition, risk tolerance. ±1.5% noise. Hard ceiling at max_price × (1+stretch), floor at 85% asking.
- **Matching** — Agents find affordable properties, score them, rank top N. ADJUSTING agents get relaxed constraints (min_beds-1, expanded type adjacency).
- **Auction resolution** — Single offer: accept/counter/reject by offer-to-ask ratio. Multi-offer: sealed-bid escalation rounds (max 3), probability-based escalation. Bidding wars emerge naturally from multiple agents targeting the same underpriced property.
- **Full simulation engine** — 26-week loop: shocks → agent entry → inventory tick → matching → offers → auction → state update → snapshot. Front-loaded agent entry (70% weeks 0-2, 30% trickle).

**Emergence confirmed:**
| Property | Signal | Sale Price vs Assessed | Offers | DOM |
|----------|--------|----------------------|--------|-----|
| LF-007 (underpriced) | 🔥 Bidding war | +12.5% | 2 offers, 2 rounds | 0 |
| OB-006 (overpriced) | 🧊 Sat and waited | +4.9% | 1 offer, 1 round | 42 |
| SE-007 (average) | ✅ Baseline | +7.5% | 17 offers, 3 rounds | 28 |

### Phase 3 — Assessment Integration (156 tests, +34 new)
*Commit: `cfe7021`*

- **Assessment gap analysis** — Compare simulated clearing price to BC Assessment value. Gap signal at ±8% threshold (under_assessed / over_assessed / within_tolerance). Confidence levels (high/medium/low) based on offer count and DOM. Market pressure score 0-10. Review recommendation (flag_for_review / within_norms / data_insufficient).
- **Neighbourhood aggregation** — Roll up property signals to neighbourhood level. Systemic signal detection: >60% same direction = systemic_under/over, >30% each = mixed, else within_norms.
- **Multi-run stability** — Run simulation N times with different seeds. Measure signal agreement percentage. Classify: stable (>80%), moderate (60-80%), unstable (<60%).
- **Report generator** — Full AnalysisReport with property results, neighbourhood summaries, stability, aggregates, and disclaimer.
- **FastAPI API** — `GET /api/health`, `POST /api/analyze`, `POST /api/analyze/stable`, `POST /api/simulate`
- **Fixes** — Inventory replenishment (Poisson new listings per week), income spread widened (5 brackets: 15/30/30/15/10%), DOM tracking in SimulationResult

### Phase 4 — Scale & Polish (187 tests, +31 new)
*Commit: `1d20806`*

- **6 macro scenarios** — baseline_2024, rate_cut_cycle, rate_hike_stress, recession, inventory_surge, hot_market. Each bundles SimulationConfig overrides + a MacroShock schedule.
- **Comparative analysis** — Run multiple scenarios on same properties, diff results. Per-property sensitivity_range_pct shows which properties are most affected by macro conditions.
- **CLI** — `python scripts/cli.py analyze|compare|smoke|scenarios` with argparse. Human-readable text reports with property tables, neighbourhood summaries, flagged-for-review lists.
- **Performance** — Pre-filtering (skip agents who can't afford cheapest listing), sorted price index, `max_matches_per_agent` cap. 1000 agents × 100 properties in 0.3s.
- **220-property dataset** — 6 neighbourhoods (added Esquimalt + Colwood). 5 deliberate under-assessed, 5 over-assessed, 10 at-market test cases.
- **README** — Full project documentation with quick start, CLI usage, API reference, scenario table.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check + version |
| `POST` | `/api/analyze` | Single-run gap analysis |
| `POST` | `/api/analyze/stable` | Multi-seed stability analysis |
| `POST` | `/api/analyze/scenario` | Run named scenario |
| `POST` | `/api/analyze/compare` | Multi-scenario comparison |
| `POST` | `/api/simulate` | Raw SimulationResult (debug) |

All responses include a disclaimer field.

---

## Macro Scenarios

| Name | Description |
|------|-------------|
| `baseline_2024` | Current conditions: 5.0% rate, balanced market |
| `rate_cut_cycle` | BoC easing: 3 cuts of 25bp at weeks 4, 12, 20 |
| `rate_hike_stress` | Emergency hikes: +100bp week 4, +50bp week 12 |
| `recession` | Economic downturn + policy response over 52 weeks |
| `inventory_surge` | Sudden listing wave: 50% more inventory at week 6 |
| `hot_market` | Low rates (3.5%) + tight supply (800 agents) |

---

## Sample Output

```
════════════════════════════════════════════════════════════════
MARKET SIMULATION — ASSESSMENT GAP ANALYSIS
════════════════════════════════════════════════════════════════
Date: 2026-03-18
Properties: 30  Sold: 30  Unsold: 0  Flagged: 6
Config: 500 agents × 26 weeks  rate=5.0%  seed=42

PROPERTY RESULTS
Folio              Assessed     Clearing    Gap%  Signal    Conf    DOM  Offers
SE-003             $740,000     $918,900  +24.2%  [UNDER]   high     14      21
LF-006             $590,000     $712,200  +20.7%  [UNDER]   high     14      81
VR-004             $480,000     $578,100  +20.4%  [UNDER]   high     21      36
...
OB-006-OVERPRICED  $1,750,000 $1,698,800   -2.9%  [OK]     low      70       1

NEIGHBOURHOOD SUMMARY
Neighbourhood      Count  Avg Gap%  Under  Over  Within  Signal
Langford               8    +13.6%      7     0       1  systemic_under
Saanich East           8    +10.5%      6     0       2  systemic_under
View Royal             7    +13.0%      6     0       1  systemic_under
Oak Bay                7     +6.2%      4     0       3  within_norms

FLAGGED FOR REVIEW (6 properties)
  SE-003  gap=+24.2%  under_assessed  high
  LF-006  gap=+20.7%  under_assessed  high
  ...
```

---

## Performance

| Config | Time |
|--------|------|
| 100 agents × 30 properties × 10 weeks | 0.13s |
| 500 agents × 30 properties × 26 weeks | 0.36s |
| 1,000 agents × 100 properties × 26 weeks | ~0.3s |
| Target: 5,000 agents × 200 properties | < 5s |

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| **No LLMs in simulation** | Economic emergence needs math, not language. 500 agents × 26 weeks costs $0.00. MiroFish-style LLM agents would be $100-1000/run. |
| **numpy Generator API** | Deterministic, fast, proper statistical distributions. No bare `random.random()`. |
| **Pydantic v2** | Validation at data boundaries (JSON → Property). Simulation internals use stdlib dataclasses for speed. |
| **Canadian mortgage math** | Semi-annual compounding is Canadian standard. OSFI stress test is regulatory requirement. Gets qualification right. |
| **Emergence-based signals** | A bidding war on a property isn't an assertion — it's what happens when 50 qualified buyers can only afford 3 properties. The signal is in the behaviour. |
| **Assessment framing** | All language frames outputs as "assessment validation indicators", never "price predictions" or "market values". Disclaimers on all output schemas. |

---

## What's Not Built Yet

- **Real BC Assessment data integration** — Currently using synthetic sample data. Needs real folio data, assessed values, and historical sales for calibration.
- **Calibration against historical sales** — The `re-simulation` project (also built today, `~/Projects/re-simulation/`) has calibration infrastructure (MAPE, bias, coverage). Could be ported.
- **Seller agent behaviour** — Currently sellers are passive (auto-accept/reject by ratio). Active sellers who adjust expectations would add realism.
- **Rental market** — Only models purchase market
- **Visualization dashboard** — CLI and API only; no web UI
- **Database persistence** — All in-memory; no PostgreSQL/Supabase yet
- **Multi-municipality** — Designed for one municipality at a time

---

## Git History

```
1d20806 feat: Phase 4 — scenarios, comparative analysis, CLI, performance, 200-property dataset
cfe7021 feat: Phase 3 — assessment gap analysis, neighbourhood aggregation, stability analysis, API
659a487 feat: Phase 2 — search, matching, bidding wars, auction mechanics, simulation engine
fd055c8 feat: Phase 1 — foundation models, financial math, agent generator, time engine
```

---

## How to Run

```bash
cd ~/Projects/market-sim
source .venv/bin/activate

# Run all 187 tests
python -m pytest tests/ -v

# Quick smoke test
python scripts/cli.py smoke

# Full analysis on sample data
python scripts/cli.py analyze --data data/properties/sample_victoria.json

# Stability analysis (10 seeds)
python scripts/cli.py analyze --data data/properties/sample_victoria.json --stable --runs 10

# Compare scenarios
python scripts/cli.py compare --data data/properties/sample_victoria.json --scenarios baseline_2024,rate_cut_cycle,recession

# Start API server
uvicorn api.main:app --reload --port 8000
```

---

*Built March 18, 2026. All amounts in CAD. Results are simulation-based indicators for assessment review prioritization, not appraisal conclusions or market value determinations.*
