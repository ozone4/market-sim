"""Page 5 — About / methodology / architecture."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

st.set_page_config(page_title="About — Market Sim", page_icon="🏠", layout="wide")

# Sidebar header
st.sidebar.markdown("## 🏠 Market Simulation Engine")
st.sidebar.markdown("**BC Assessment Validation Tool**")
st.sidebar.divider()

_ROOT = Path(__file__).parent.parent.parent  # project root

# ── Page content ───────────────────────────────────────────────────────────────
st.title("About Market Sim")

st.markdown("""
## Project Description

**market-sim** is a multi-agent real estate market simulation engine for BC Assessment validation.

The system generates demographically realistic buyer agents that compete for properties over a
configurable time horizon. Emergent market signals — bidding wars, price reductions,
days-on-market accumulation — are compared against BC Assessment values to identify properties
that may warrant reassessment review.

Data is sourced from BC Assessment rolls (30- and 220-property Victoria CMA samples) and
demographic weights are derived from the 2021 Statistics Canada Census for Greater Victoria CMA,
adjusted to 2024 dollars (~+12% inflation).

**Source code:** [github.com/ozone4/market-sim](https://github.com/ozone4/market-sim)
""")

st.divider()

st.markdown("## How It Works")
st.markdown("""
1. **Property loading** — BC Assessment JSON properties are validated with Pydantic v2 models.
2. **Agent generation** — Buyer agents are sampled from census-derived income and household-type
   distributions. Each agent receives a financial qualification (max purchase price) computed
   using the Canadian stress test (GDS/TDS ratios).
3. **Weekly simulation loop** — Over 26 weeks (configurable):
   - Macro shocks are applied (rate changes, recession events, inventory surges).
   - New agents enter the market (front-loaded by default).
   - The inventory tracker increments days-on-market, applies price reductions, and expires stale listings.
   - Agents score properties via a 0–100 preference model and decide to bid, wait, or adjust.
   - Offer resolution: single-offer acceptance/counter/rejection logic or multi-offer sealed-bid
     escalation (up to 3 rounds).
4. **Gap analysis** — Each sold property's clearing price is compared to its BC Assessment value.
   A gap >8% flags under-assessment; a gap <-8% flags over-assessment.
5. **Neighbourhood aggregation** — If >60% of a neighbourhood's properties share one signal,
   a systemic signal is raised.
6. **Stability analysis** — Run multiple seeds to measure how consistently a property produces the
   same gap signal (stable >80%, moderate 60–80%, unstable <60%).
""")

st.divider()

st.markdown("## Architecture")

arch_path = _ROOT / "docs" / "ARCHITECTURE.md"
if arch_path.exists():
    arch_text = arch_path.read_text()
    # Strip the H1 title (already shown above)
    lines = arch_text.splitlines()
    body_lines = [ln for ln in lines if not ln.startswith("# Architecture")]
    st.markdown("\n".join(body_lines))
else:
    st.markdown("""
```
market-sim/
├── sim/
│   ├── agents/       — Census-derived buyer agent generation + financial math
│   ├── engine/       — Weekly simulation loop, auction resolution, matching
│   ├── market/       — Clock, inventory, macro shocks
│   ├── properties/   — JSON loader, Pydantic property models
│   └── analysis/     — Gap analysis, neighbourhood aggregation, stability, reports
├── api/              — FastAPI REST service
├── dashboard/        — Streamlit visual interface (this app)
├── data/properties/  — BC Assessment sample datasets
└── tests/            — pytest test suite (187 tests)
```
""")

st.divider()

st.markdown("## Scenarios")
st.markdown("""
| Scenario | Description |
|----------|-------------|
| **Baseline 2024** | 5.0% rate, balanced market |
| **Rate Cut Cycle** | BoC easing: 3 cuts of 25bp at weeks 4, 12, 20 |
| **Rate Hike Stress Test** | Emergency hikes: +100bp at week 4, +50bp at week 12 |
| **Recession** | Economic downturn with income shock + rate cut response |
| **Inventory Surge** | High replenishment + listing wave at week 6 |
| **Hot Market** | Low rates (3.5%), 800 agents, tight supply |
""")

st.divider()

st.error(
    "**Disclaimer:** Results produced by this tool are indicators for assessment review "
    "prioritization only — they are not appraisal conclusions, market value determinations, "
    "or legal assessments. Simulation outputs are emergent from stylized agent behavior and "
    "should not be used as the sole basis for any assessment decision. All amounts in CAD."
)
