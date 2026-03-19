# Methodology

## What the Simulation Does

`market-sim` runs a multi-agent simulation of a residential real estate market. It does not predict prices or model appraisal outcomes. It measures how simulated buyer demand interacts with a set of properties at their assessed values, and signals whether the market would consistently clear above, below, or within tolerance of each BC Assessment value.

## Agent Generation

Buyer agents are generated from Statistics Canada 2021 Census data for Greater Victoria CMA (adjusted to 2024 dollars). Each agent receives:

- **Household type** sampled from the CMA distribution (SINGLE_YOUNG, COUPLE_NO_KIDS, COUPLE_WITH_KIDS, SINGLE_PARENT, DOWNSIZER, RETIREE, INVESTOR, NEW_TO_AREA)
- **Income** sampled from a five-band distribution calibrated to the regional income spread
- **Financial qualification** computed using Canadian mortgage stress-test math (GDS/TDS ratios, Bank of Canada qualifying rate)
- **Preferences** derived from household type (bedroom requirements, preferred property types, suite/garage needs)
- **Behavior parameters** (urgency, risk tolerance, patience in weeks, bid escalation tolerance)

## Market Mechanics

Each simulation week:
1. New agents enter the market per the entry schedule
2. Optional new inventory is added (replenishment)
3. Days-on-market (DOM) increments for all active listings; price reductions apply at 21/42/63 days; listings expire at 90 days
4. Each active agent scores available properties (0-100 PropertyScore) based on affordability, size fit, property type, location, condition, and features
5. Agents decide whether to BID, WAIT, ADJUST criteria, or EXIT
6. All offers on each property are resolved:
   - Single offer: accepted if ≥ 95-98% of asking (threshold depends on market temperature)
   - Multiple offers: sealed-bid escalation rounds; highest bid after up to 3 rounds wins

## Assessment Gap Signal

For each property that sells, the gap is computed as:

```
gap_pct = (clearing_price - assessed_value) / assessed_value × 100
```

Thresholds:
- `|gap_pct| ≤ 8%` → **within_tolerance** — assessment is consistent with simulated market
- `gap_pct > 8%` → **under_assessed** — market would pay significantly more than assessed value
- `gap_pct < -8%` → **over_assessed** — market would not support the assessment

The 8% threshold reflects the combination of markup variance (±5%), seasonal effects, and agent heterogeneity. Properties within this band are unlikely to warrant review based on market behavior alone.

## Confidence Scoring

Confidence reflects the reliability of a single-run signal:

| Level | Conditions |
|-------|-----------|
| high | ≥ 3 offers received, DOM < 30 days |
| medium | 1-2 offers, DOM 30-60 days |
| low | 0 offers (expired unsold), DOM > 60 days, or sold only after price reductions |

For multi-run stability analysis, confidence is also informed by cross-seed signal agreement.

## Market Pressure Score

A 0-10 score summarizing demand intensity for a property:

| Component | Score |
|-----------|-------|
| 0 offers | base 0 |
| 1 offer | base 2 |
| 2-3 offers | base 4 |
| 4-5 offers | base 6 |
| 6-10 offers | base 8 |
| >10 offers | base 10 |
| DOM < 14 days | +1 |
| DOM 14-30 days | ±0 |
| DOM 30-60 days | -1 |
| DOM > 60 days | -2 |
| 2 auction rounds | +0.5 |
| 3+ auction rounds | +1 |

Score is clamped to [0, 10].

## Systemic Signals

Neighbourhood-level systemic signals aggregate property-level gap signals:

- **systemic_under**: > 60% of properties signal `under_assessed`
- **systemic_over**: > 60% of properties signal `over_assessed`
- **mixed**: > 30% each direction
- **within_norms**: all other cases

A systemic signal suggests that assessment values for an entire neighbourhood may need recalibration, independent of any individual property review.

## Stability Analysis

Running the simulation multiple times with different random seeds (different agent populations and bidding sequences) measures how robust the gap signal is:

- **stable** (> 80% agreement): The signal is likely driven by fundamental supply-demand dynamics, not random variation
- **moderate** (60-80% agreement): Some confidence, but additional data would strengthen the signal
- **unstable** (< 60% agreement): Insufficient signal — the property's market outcome is highly sensitive to buyer mix

## Limitations

1. **Fixed buyer population**: The simulation does not model seller strategy (pricing, timing, withdrawal)
2. **No external comps**: Agents do not reference comparable sales when forming bids; they use financial qualification and preference scoring only
3. **Closed market**: No cross-municipality demand, no investor speculation beyond what's in the household type distribution
4. **Stylized auction mechanics**: The bidding war model simplifies real negotiation dynamics
5. **Properties only**: The model does not capture land value vs. improvement value, which matters for BC Assessment methodology
6. **Results are probabilistic**: Identical properties may clear at different prices across runs; use stability analysis to assess signal robustness

These limitations mean simulation signals should be used for **review prioritization**, not as appraisal conclusions or market value determinations.
