"""
Multi-run stability analysis.

Runs the simulation N times with different random seeds and measures how
consistently each property receives the same gap signal. Stable signals
(>80% agreement across seeds) provide stronger evidence for review
prioritization than single-run results.

All amounts in CAD.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from sim.analysis.assessment_gap import analyze_all_gaps
from sim.engine.simulation import SimulationConfig, run_simulation
from sim.properties.models import Property


@dataclass
class StabilityResult:
    """Stability metrics for one property across N simulation runs."""

    folio_id: str
    num_runs: int
    clearing_prices: list[float]       # One entry per run (0.0 if unsold in that run)
    gap_signals: list[str]             # One entry per run
    mean_clearing_price: float
    std_clearing_price: float
    p10_clearing_price: float
    p90_clearing_price: float
    dominant_signal: str               # Most common gap_signal
    signal_agreement_pct: float        # % of runs agreeing with dominant signal
    stability: str                     # "stable" (>80%), "moderate" (60-80%), "unstable" (<60%)


# ─── Public API ───────────────────────────────────────────────────────────────

def run_stability_analysis(
    properties: list[Property],
    base_config: SimulationConfig,
    num_runs: int = 10,
    seed_offset: int = 1000,
) -> dict[str, StabilityResult]:
    """
    Run the simulation N times with different seeds and measure signal stability.

    Each run uses seed = base_config.seed + seed_offset * run_index so
    results are fully reproducible given the same inputs.

    Parameters
    ----------
    properties:
        Properties to simulate (passed to run_simulation unchanged).
    base_config:
        Base simulation configuration. Only the seed is varied across runs.
    num_runs:
        Number of independent runs.
    seed_offset:
        Seed increment between runs (default 1000 to avoid correlation).

    Returns
    -------
    dict mapping folio_id → StabilityResult for every property in the list.
    """
    per_folio_prices: dict[str, list[float]] = {p.folio_id: [] for p in properties}
    per_folio_signals: dict[str, list[str]] = {p.folio_id: [] for p in properties}

    for run_idx in range(num_runs):
        seed = base_config.seed + seed_offset * run_idx
        config = SimulationConfig(
            num_agents=base_config.num_agents,
            num_weeks=base_config.num_weeks,
            contract_rate=base_config.contract_rate,
            seed=seed,
            initial_markup=base_config.initial_markup,
            markup_variance=base_config.markup_variance,
            agent_entry_mode=base_config.agent_entry_mode,
            shocks=list(base_config.shocks),
            replenishment_rate=base_config.replenishment_rate,
            replenishment_variance=base_config.replenishment_variance,
        )
        result = run_simulation(properties, config)
        gaps = analyze_all_gaps(result, properties)

        for gap in gaps:
            per_folio_prices[gap.folio_id].append(gap.simulated_clearing_price)
            per_folio_signals[gap.folio_id].append(gap.gap_signal)

    output: dict[str, StabilityResult] = {}

    for prop in properties:
        fid = prop.folio_id
        prices = per_folio_prices[fid]
        signals = per_folio_signals[fid]

        # Statistics on sold-only prices
        sold_prices = [p for p in prices if p > 0.0]
        if sold_prices:
            mean_price = statistics.mean(sold_prices)
            std_price = statistics.stdev(sold_prices) if len(sold_prices) > 1 else 0.0
            arr = sorted(sold_prices)
            n = len(arr)
            p10_idx = max(0, int(n * 0.10) - 1)
            p90_idx = min(n - 1, int(n * 0.90))
            p10_price = arr[p10_idx]
            p90_price = arr[p90_idx]
        else:
            mean_price = 0.0
            std_price = 0.0
            p10_price = 0.0
            p90_price = 0.0

        # Dominant signal and agreement
        signal_counts: dict[str, int] = {}
        for s in signals:
            signal_counts[s] = signal_counts.get(s, 0) + 1
        dominant_signal = max(signal_counts, key=lambda k: signal_counts[k])
        agreement_pct = signal_counts[dominant_signal] / num_runs * 100.0

        if agreement_pct > 80.0:
            stability = "stable"
        elif agreement_pct >= 60.0:
            stability = "moderate"
        else:
            stability = "unstable"

        output[fid] = StabilityResult(
            folio_id=fid,
            num_runs=num_runs,
            clearing_prices=prices,
            gap_signals=signals,
            mean_clearing_price=round(mean_price, 2),
            std_clearing_price=round(std_price, 2),
            p10_clearing_price=round(p10_price, 2),
            p90_clearing_price=round(p90_price, 2),
            dominant_signal=dominant_signal,
            signal_agreement_pct=round(agreement_pct, 1),
            stability=stability,
        )

    return output
