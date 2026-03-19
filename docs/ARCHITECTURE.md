# Architecture

## System Overview

`market-sim` is a multi-agent real estate market simulation engine for BC Assessment validation. It simulates demographically realistic buyer agents competing for properties over a 26-week period, producing emergent price signals (bidding wars, price reductions, market clearing) that can be compared against BC Assessment values.

## Module Map

```
market-sim/
├── sim/
│   ├── agents/
│   │   ├── financial.py     — Canadian mortgage math (GDS/TDS qualification)
│   │   ├── generator.py     — Census-derived agent pool generation
│   │   ├── models.py        — BuyerAgent, FinancialProfile, BehaviorProfile, PreferenceProfile
│   │   ├── preferences.py   — PropertyScore (0-100), per-type scoring weights
│   │   └── strategy.py      — Weekly action selection, bid amount calculation
│   ├── engine/
│   │   ├── auction.py       — Offer resolution: single offer, multi-offer bidding wars
│   │   ├── context.py       — MarketContext: temperature, seasonality, rate
│   │   ├── matching.py      — find_matches: affordability + preference filtering
│   │   └── simulation.py    — run_simulation(): main weekly loop, SimulationConfig, SimulationResult
│   ├── market/
│   │   ├── clock.py         — SimulationClock: weekly ticks, seasons
│   │   ├── inventory.py     — MarketInventory: DOM tracking, price reductions, expiry
│   │   └── shocks.py        — MacroShock: rate changes, recession impacts
│   ├── properties/
│   │   ├── loader.py        — JSON ingestion, Pydantic validation
│   │   └── models.py        — Property, Listing, Location, Features
│   └── analysis/
│       ├── assessment_gap.py — Per-property gap signal vs BC Assessment
│       ├── neighbourhood.py  — Neighbourhood-level systemic signal aggregation
│       ├── stability.py      — Multi-seed stability measurement
│       └── report.py         — Full AnalysisReport generator
├── api/
│   ├── main.py              — FastAPI app entry point
│   ├── routes.py            — Endpoint handlers
│   └── schemas.py           — Pydantic v2 request/response models
├── data/
│   └── properties/
│       └── sample_victoria.json — 30 BC Assessment properties
├── scripts/
│   └── run_smoke_test.py    — Human-readable simulation output
└── tests/                   — pytest test suite
```

## Data Flow

```
JSON properties
      │
      ▼
load_properties_from_json()
      │
      ▼
run_simulation(properties, config)
      │
      ├── generate_buyer_pool()          ← Census demographics
      │         │
      │         └── BuyerAgent × N      (income, savings, debts, equity, preferences)
      │
      ├── MarketInventory.add_listing()  ← Week 0 listings + replenishment
      │
      └── Weekly loop (26 weeks):
              │
              ├── Apply MacroShocks
              ├── Enter new agents
              ├── Replenish inventory (optional)
              ├── inventory.tick()       ← DOM++, price reductions, expiry
              ├── find_matches()         ← Score properties per agent
              ├── agent_weekly_action()  ← BID / WAIT / ADJUST / EXIT
              ├── resolve_offers()       ← Single-offer or bidding war
              └── Record WeeklySnapshot
                          │
                          ▼
                  SimulationResult
                          │
                          ▼
              analyze_all_gaps()         ← Compare clearing to assessed
                          │
                          ▼
          summarize_all_neighbourhoods() ← Systemic signals
                          │
                          ▼
              generate_report()          ← AnalysisReport
```

## Key Design Decisions

- **Deterministic**: All randomness flows through `np.random.default_rng(seed)`. Same config → same result.
- **No LLMs**: All simulation logic is rule-based. Agent decisions use parameterized strategies.
- **Pydantic v2**: Property and Listing models use Pydantic BaseModel for validation. Simulation dataclasses use Python stdlib `dataclass`.
- **Separation of concerns**: The simulation engine does not know about gap analysis. Analysis operates on `SimulationResult`.
- **Census-grounded**: Agent demographics use 2021 StatsCan data for Greater Victoria CMA, adjusted to 2024 dollars.
