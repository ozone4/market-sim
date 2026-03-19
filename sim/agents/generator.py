"""
Generate buyer agents from census-derived demographic distributions.

Uses StatsCan-derived income and household type distributions for
Greater Victoria CMA (Census Metropolitan Area, 2021 Census adjusted
to 2024 dollars ~+12% inflation).

Each agent gets: household type → income → savings → debts →
homeownership state (for equity) → preference profile → behavior profile.
Financial qualification (max_purchase_price) is computed at generation
time so search/matching can filter without recomputing.

All distributions are parameterized and can be overridden for
different regions or scenarios.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from sim.agents.financial import calculate_max_purchase_price
from sim.agents.models import (
    AgentStatus,
    BehaviorProfile,
    BuyerAgent,
    FinancialProfile,
    HouseholdType,
    PreferenceProfile,
)

# ─── Income distribution ─────────────────────────────────────────────────────
# Greater Victoria CMA (2021 Census, Table 11-10-0190-01, ~+12% for 2024 dollars)
# Keys are (min, max) inclusive bands; values are fraction of households.
VICTORIA_INCOME_DISTRIBUTION: dict[tuple[float, float], float] = {
    (30_000,  50_000): 0.15,
    (50_000,  75_000): 0.20,
    (75_000, 100_000): 0.20,
    (100_000, 125_000): 0.15,
    (125_000, 150_000): 0.12,
    (150_000, 200_000): 0.10,
    (200_000, 300_000): 0.06,
    (300_000, 500_000): 0.02,
}

# ─── Household type distribution ─────────────────────────────────────────────
# Victoria CMA Census 2021 (household structure proportions)
VICTORIA_HOUSEHOLD_DISTRIBUTION: dict[HouseholdType, float] = {
    HouseholdType.SINGLE_YOUNG:      0.12,
    HouseholdType.COUPLE_NO_KIDS:    0.22,
    HouseholdType.COUPLE_WITH_KIDS:  0.20,
    HouseholdType.SINGLE_PARENT:     0.08,
    HouseholdType.DOWNSIZER:         0.12,
    HouseholdType.RETIREE:           0.10,
    HouseholdType.INVESTOR:          0.10,
    HouseholdType.NEW_TO_AREA:       0.06,
}

# ─── Per-type demographic parameters ─────────────────────────────────────────
# Each entry configures how to generate a household of that type.
# income_quintiles: which quintile bands (1=lowest, 5=highest) to draw from
#                   (as list of weights across quintiles 1-5)
# savings_multiplier_range: (min, max) × annual income saved
# debt_probability: chance of having existing monthly debts
# debt_monthly_range: (min, max) for monthly debt payments if they have debts
# ownership_probability: chance of already owning a home (has equity)
# current_home_value_range: (min_pct, max_pct) × income as proxy for home value
#   (used only when ownership_probability fires)
# mortgage_remaining_pct_range: (min, max) fraction of home value still owed

_TYPE_PARAMS: dict[HouseholdType, dict] = {
    HouseholdType.SINGLE_YOUNG: dict(
        income_quintile_weights=[0.30, 0.35, 0.25, 0.08, 0.02],
        savings_multiplier_range=(0.3, 1.0),
        debt_probability=0.45,
        debt_monthly_range=(200, 600),
        ownership_probability=0.05,
        current_home_value_range=(3.0, 5.0),
        mortgage_remaining_pct_range=(0.70, 0.90),
        min_bedrooms=1,
        preferred_types=["condo", "townhouse"],
        urgency_range=(0.3, 0.7),
        patience_weeks_range=(16, 40),
        risk_tolerance_range=(0.4, 0.8),
        adjustment_after_losses_range=(2, 4),
    ),
    HouseholdType.COUPLE_NO_KIDS: dict(
        income_quintile_weights=[0.10, 0.25, 0.35, 0.20, 0.10],
        savings_multiplier_range=(0.6, 2.0),
        debt_probability=0.40,
        debt_monthly_range=(200, 800),
        ownership_probability=0.35,
        current_home_value_range=(4.0, 7.0),
        mortgage_remaining_pct_range=(0.50, 0.80),
        min_bedrooms=2,
        preferred_types=["condo", "townhouse", "single_family_detached"],
        urgency_range=(0.3, 0.7),
        patience_weeks_range=(16, 40),
        risk_tolerance_range=(0.4, 0.7),
        adjustment_after_losses_range=(2, 5),
    ),
    HouseholdType.COUPLE_WITH_KIDS: dict(
        income_quintile_weights=[0.08, 0.20, 0.35, 0.25, 0.12],
        savings_multiplier_range=(0.5, 1.8),
        debt_probability=0.55,
        debt_monthly_range=(400, 1200),
        ownership_probability=0.55,
        current_home_value_range=(4.5, 8.0),
        mortgage_remaining_pct_range=(0.45, 0.75),
        min_bedrooms=3,
        preferred_types=["single_family_detached", "townhouse"],
        urgency_range=(0.5, 0.9),
        patience_weeks_range=(12, 32),
        risk_tolerance_range=(0.3, 0.6),
        adjustment_after_losses_range=(2, 4),
    ),
    HouseholdType.SINGLE_PARENT: dict(
        income_quintile_weights=[0.35, 0.35, 0.20, 0.08, 0.02],
        savings_multiplier_range=(0.2, 0.8),
        debt_probability=0.60,
        debt_monthly_range=(300, 800),
        ownership_probability=0.20,
        current_home_value_range=(3.0, 5.0),
        mortgage_remaining_pct_range=(0.60, 0.85),
        min_bedrooms=2,
        preferred_types=["townhouse", "condo", "single_family_detached"],
        urgency_range=(0.5, 0.9),
        patience_weeks_range=(12, 28),
        risk_tolerance_range=(0.2, 0.5),
        adjustment_after_losses_range=(2, 3),
    ),
    HouseholdType.DOWNSIZER: dict(
        income_quintile_weights=[0.05, 0.15, 0.30, 0.30, 0.20],
        savings_multiplier_range=(1.5, 4.0),
        debt_probability=0.20,
        debt_monthly_range=(100, 400),
        ownership_probability=0.95,
        current_home_value_range=(6.0, 12.0),
        mortgage_remaining_pct_range=(0.05, 0.30),
        min_bedrooms=2,
        preferred_types=["townhouse", "condo", "single_family_detached"],
        urgency_range=(0.2, 0.6),
        patience_weeks_range=(20, 52),
        risk_tolerance_range=(0.3, 0.6),
        adjustment_after_losses_range=(3, 6),
    ),
    HouseholdType.RETIREE: dict(
        income_quintile_weights=[0.10, 0.20, 0.30, 0.25, 0.15],
        savings_multiplier_range=(2.0, 6.0),
        debt_probability=0.10,
        debt_monthly_range=(100, 300),
        ownership_probability=0.90,
        current_home_value_range=(6.0, 14.0),
        mortgage_remaining_pct_range=(0.0, 0.20),
        min_bedrooms=1,
        preferred_types=["condo", "townhouse"],
        urgency_range=(0.1, 0.4),
        patience_weeks_range=(26, 52),
        risk_tolerance_range=(0.2, 0.5),
        adjustment_after_losses_range=(4, 8),
    ),
    HouseholdType.INVESTOR: dict(
        income_quintile_weights=[0.05, 0.10, 0.25, 0.35, 0.25],
        savings_multiplier_range=(1.0, 4.0),
        debt_probability=0.50,
        debt_monthly_range=(500, 2000),
        ownership_probability=0.80,
        current_home_value_range=(4.0, 10.0),
        mortgage_remaining_pct_range=(0.30, 0.70),
        min_bedrooms=1,
        preferred_types=["condo", "townhouse", "duplex"],
        urgency_range=(0.4, 0.8),
        patience_weeks_range=(16, 40),
        risk_tolerance_range=(0.6, 0.9),
        adjustment_after_losses_range=(2, 4),
    ),
    HouseholdType.NEW_TO_AREA: dict(
        income_quintile_weights=[0.10, 0.20, 0.35, 0.25, 0.10],
        savings_multiplier_range=(0.5, 2.0),
        debt_probability=0.40,
        debt_monthly_range=(200, 700),
        ownership_probability=0.30,
        current_home_value_range=(3.5, 6.0),
        mortgage_remaining_pct_range=(0.50, 0.80),
        min_bedrooms=2,
        preferred_types=[],  # Open to anything — don't know area well
        urgency_range=(0.6, 1.0),
        patience_weeks_range=(8, 24),
        risk_tolerance_range=(0.4, 0.7),
        adjustment_after_losses_range=(1, 3),
    ),
}


def _build_income_bands(
    distribution: dict[tuple[float, float], float]
) -> tuple[list[tuple[float, float]], list[float]]:
    """Split distribution dict into parallel bands and cumulative weights."""
    bands = list(distribution.keys())
    weights = list(distribution.values())
    total = sum(weights)
    normalized = [w / total for w in weights]
    return bands, normalized


def _sample_income(
    rng: np.random.Generator,
    distribution: dict[tuple[float, float], float],
    quintile_weights: list[float],
) -> float:
    """
    Sample an income value.

    First selects a quintile band using the type-specific quintile weights,
    then uniformly samples within that band.

    Quintile assignment maps from 5 quintiles to the len(distribution) bands
    by binning — if distribution has 8 bands, quintiles map to roughly 1-2 bands each.
    """
    bands, global_weights = _build_income_bands(distribution)
    n_bands = len(bands)
    n_quintiles = len(quintile_weights)

    # Map quintile weights onto the bands (proportional assignment)
    band_weights = np.zeros(n_bands)
    for q_idx, q_weight in enumerate(quintile_weights):
        # Each quintile covers a proportional slice of the bands
        band_start = int(q_idx / n_quintiles * n_bands)
        band_end = int((q_idx + 1) / n_quintiles * n_bands)
        band_end = max(band_end, band_start + 1)  # At least one band per quintile
        band_end = min(band_end, n_bands)
        for b in range(band_start, band_end):
            band_weights[b] += q_weight / (band_end - band_start)

    # Normalize and sample
    total_w = band_weights.sum()
    if total_w <= 0:
        band_weights = np.array(global_weights)
    else:
        band_weights /= total_w

    cumulative = np.cumsum(band_weights)
    u = rng.random()
    band_idx = int(np.searchsorted(cumulative, u))
    band_idx = min(band_idx, n_bands - 1)

    low, high = bands[band_idx]
    return rng.uniform(low, high)


def generate_buyer_pool(
    num_agents: int,
    rng: np.random.Generator,
    contract_rate: float = 0.05,
    income_distribution: Optional[dict[tuple[float, float], float]] = None,
    household_distribution: Optional[dict[HouseholdType, float]] = None,
    entry_week: int = 0,
) -> list[BuyerAgent]:
    """
    Generate a pool of demographically realistic buyer agents.

    Parameters
    ----------
    num_agents:
        Number of agents to generate.
    rng:
        NumPy random Generator (use np.random.default_rng(seed) for reproducibility).
    contract_rate:
        Current mortgage contract rate (used for financial qualification).
    income_distribution:
        Override for Victoria income distribution. Default: VICTORIA_INCOME_DISTRIBUTION.
    household_distribution:
        Override for household type distribution. Default: VICTORIA_HOUSEHOLD_DISTRIBUTION.
    entry_week:
        Simulation week at which these agents enter the market.

    Returns
    -------
    list[BuyerAgent]
        Agents with financial qualification (max_purchase_price) pre-computed.
    """
    if income_distribution is None:
        income_distribution = VICTORIA_INCOME_DISTRIBUTION
    if household_distribution is None:
        household_distribution = VICTORIA_HOUSEHOLD_DISTRIBUTION

    # Build household type sampling arrays
    ht_types = list(household_distribution.keys())
    ht_weights = np.array(list(household_distribution.values()), dtype=float)
    ht_weights /= ht_weights.sum()
    ht_cumulative = np.cumsum(ht_weights)

    agents: list[BuyerAgent] = []

    for i in range(num_agents):
        agent_id = f"agent_{entry_week:04d}_{i:05d}"

        # --- Sample household type ---
        u = rng.random()
        ht_idx = int(np.searchsorted(ht_cumulative, u))
        ht_idx = min(ht_idx, len(ht_types) - 1)
        household_type = ht_types[ht_idx]
        params = _TYPE_PARAMS[household_type]

        # --- Sample income ---
        annual_income = _sample_income(
            rng, income_distribution, params["income_quintile_weights"]
        )

        # --- Savings ---
        savings_mult_low, savings_mult_high = params["savings_multiplier_range"]
        savings_mult = rng.uniform(savings_mult_low, savings_mult_high)
        savings = annual_income * savings_mult

        # --- Existing debts ---
        has_debts = rng.random() < params["debt_probability"]
        if has_debts:
            debt_low, debt_high = params["debt_monthly_range"]
            existing_monthly_debts = rng.uniform(debt_low, debt_high)
        else:
            existing_monthly_debts = 0.0

        # --- Current homeownership (for equity) ---
        is_owner = rng.random() < params["ownership_probability"]
        if is_owner:
            home_val_low, home_val_high = params["current_home_value_range"]
            current_home_value = annual_income * rng.uniform(home_val_low, home_val_high)
            mort_pct_low, mort_pct_high = params["mortgage_remaining_pct_range"]
            current_mortgage_balance = current_home_value * rng.uniform(mort_pct_low, mort_pct_high)
            is_first_time_buyer = False
        else:
            current_home_value = 0.0
            current_mortgage_balance = 0.0
            is_first_time_buyer = True

        financial = FinancialProfile(
            annual_income=annual_income,
            savings=savings,
            existing_monthly_debts=existing_monthly_debts,
            current_home_value=current_home_value,
            current_mortgage_balance=current_mortgage_balance,
            is_first_time_buyer=is_first_time_buyer,
        )

        # --- Compute max purchase price (hard qualification ceiling) ---
        max_price = calculate_max_purchase_price(
            annual_income=annual_income,
            down_payment=financial.total_down_payment,
            monthly_debts=existing_monthly_debts,
            contract_rate=contract_rate,
        )

        # --- Preference profile ---
        min_bedrooms = params["min_bedrooms"]
        preferred_types = list(params["preferred_types"])

        preferences = PreferenceProfile(
            min_bedrooms=min_bedrooms,
            max_price=max_price,
            preferred_property_types=preferred_types,
            needs_suite=(household_type == HouseholdType.INVESTOR and rng.random() < 0.6),
            needs_garage=(
                household_type in (HouseholdType.COUPLE_WITH_KIDS, HouseholdType.DOWNSIZER)
                and rng.random() < 0.4
            ),
        )

        # --- Behavior profile ---
        urgency = float(rng.uniform(*params["urgency_range"]))
        risk_tolerance = float(rng.uniform(*params["risk_tolerance_range"]))
        patience_weeks = int(rng.integers(*params["patience_weeks_range"]))
        adj_losses = int(rng.integers(*params["adjustment_after_losses_range"]))
        # Urgency → slightly higher bid stretch tolerance
        max_bid_stretch = 0.03 + urgency * 0.07  # 3-10%

        behavior = BehaviorProfile(
            urgency=urgency,
            risk_tolerance=risk_tolerance,
            patience_weeks=patience_weeks,
            adjustment_after_losses=adj_losses,
            max_bid_stretch=max_bid_stretch,
        )

        agent = BuyerAgent(
            id=agent_id,
            household_type=household_type,
            financial=financial,
            preferences=preferences,
            behavior=behavior,
            status=AgentStatus.ENTERING,
            entry_week=entry_week,
        )
        agents.append(agent)

    return agents
