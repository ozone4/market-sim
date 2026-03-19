# Calibration Guide

## SimulationConfig Parameters

### Core Parameters

| Parameter | Default | Range | Effect |
|-----------|---------|-------|--------|
| `num_agents` | 500 | 50-5000 | Pool of buyers competing over properties. Lower → less competition, more unsold. Higher → more bidding wars. 500 matches Victoria CMA active buyer estimate. |
| `num_weeks` | 26 | 8-52 | Simulation duration in weeks (~6 months). Should be ≥ 90/7 ≈ 13 to allow all listings to expire if unsold. |
| `contract_rate` | 0.05 | 0.03-0.10 | Current mortgage contract rate. Directly controls agent qualification (max purchase price). Matches Bank of Canada rate environment. |
| `seed` | 42 | any int | Random seed. Controls all stochastic outcomes. Increment for different realizations. |

### Asking Price Strategy

| Parameter | Default | Effect |
|-----------|---------|--------|
| `initial_markup` | 0.03 | Asking price = assessed × (1 + markup). 0.03 = 3% above assessed. Negative values list below assessed. |
| `markup_variance` | 0.05 | Per-property random ±variance added to markup. Creates realistic spread in asking prices. |

Combined effect: if assessed = $800,000, markup = 0.03, variance = 0.05, then asking is in range $800K × (1 - 0.02) to $800K × (1 + 0.08) = $784K to $864K.

### Agent Entry Pattern

| `agent_entry_mode` | Effect |
|---------------------|--------|
| `front_loaded` (default) | 70% enter weeks 0-2, 30% trickle in over remaining weeks. Simulates spring market surge. |
| `gradual` | Equal batches each week. Simulates steady market. |
| `random` | Poisson process. Simulates unpredictable entry. |

### Inventory Replenishment

| Parameter | Default | Effect |
|-----------|---------|--------|
| `replenishment_rate` | 0.0 | Fraction of initial inventory added per week. 0.05 = 5% → with 30 properties, ~1.5 new listings/week. Set to 0.05-0.10 for longer simulations or to prevent market clearing too early. |
| `replenishment_variance` | 0.02 | ±Jitter on per-week new listing count (2%). Controls week-to-week variation in new supply. |

New listings are clones of random existing properties with:
- New folio_id: `{original}-R{week}`
- Assessed value jittered ±5%
- Fresh asking price using the same markup strategy

## Macro Shocks

Shocks can be injected at any week:

```python
from sim.market.shocks import MacroShock, ShockType

# Rate hike at week 4
rate_shock = MacroShock(
    week=4,
    shock_type=ShockType.RATE_CHANGE,
    params={"new_rate": 0.065},
)

# Recession affecting 15% of buyers at week 8
recession = MacroShock(
    week=8,
    shock_type=ShockType.RECESSION,
    params={"income_impact": -0.05, "affected_pct": 0.15},
)

config = SimulationConfig(shocks=[rate_shock, recession])
```

## Tuning for Different Market Conditions

### Hot market (strong demand, few listings)
```python
SimulationConfig(
    num_agents=700,
    num_weeks=26,
    contract_rate=0.045,
    initial_markup=0.05,
    agent_entry_mode="front_loaded",
    replenishment_rate=0.02,
)
```

### Balanced market
```python
SimulationConfig(
    num_agents=500,
    num_weeks=26,
    contract_rate=0.05,
    initial_markup=0.03,
    agent_entry_mode="gradual",
    replenishment_rate=0.05,
)
```

### Cold market (weak demand, many expired)
```python
SimulationConfig(
    num_agents=200,
    num_weeks=26,
    contract_rate=0.07,
    initial_markup=0.01,
    agent_entry_mode="gradual",
    replenishment_rate=0.0,
)
```

## Interpreting Results

### When too many properties sell in early weeks
Symptom: 20+ empty weeks after week 6.
Fix: Increase `replenishment_rate` to 0.05-0.10, or decrease `num_agents`.

### When too few properties sell
Symptom: > 80% properties expire unsold.
Fix: Decrease `contract_rate`, decrease `initial_markup`, or increase `num_agents`.

### When all signals are "data_insufficient"
Symptom: All properties have confidence = "low".
Fix: Increase `num_agents`, decrease `contract_rate`, or reduce `initial_markup` so prices are within buyer qualification range.

### When signals are unstable across runs
Symptom: `stability = "unstable"` for most properties.
Fix: Increase `num_agents` (more buyers → more consistent outcomes), or check that property prices are within range of the buyer pool.

## Analysis Parameters

Gap threshold (8%) and review threshold (15%) are hardcoded in `sim/analysis/assessment_gap.py`. To change them, edit the `analyze_property_gap()` function:

```python
# Gap signal thresholds (line ~90)
if abs(gap_pct) <= 8.0:   # ← adjust 8.0
    gap_signal = "within_tolerance"

# Review recommendation (line ~120)
if abs(gap_pct) > 15.0 and conf != "low":   # ← adjust 15.0
    review_recommendation = "flag_for_review"
```
