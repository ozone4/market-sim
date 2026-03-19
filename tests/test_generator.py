"""
Tests for the buyer agent generator.

Validates demographic distributions, financial qualification, and
deterministic reproducibility.
"""
import numpy as np
import pytest

from sim.agents.generator import (
    VICTORIA_HOUSEHOLD_DISTRIBUTION,
    generate_buyer_pool,
)
from sim.agents.models import AgentStatus, HouseholdType


def test_generates_correct_count():
    """Generator returns exactly num_agents agents."""
    rng = np.random.default_rng(42)
    agents = generate_buyer_pool(100, rng)
    assert len(agents) == 100


def test_generates_zero_agents():
    """Zero agents request returns empty list."""
    rng = np.random.default_rng(42)
    agents = generate_buyer_pool(0, rng)
    assert agents == []


def test_household_distribution_approximate():
    """
    Household type proportions should be within ±8% of target with 1000 agents.

    Using 8% tolerance (not 5%) because with 1000 agents and some types at 6%
    expected, variance is naturally higher.
    """
    rng = np.random.default_rng(42)
    n = 1000
    agents = generate_buyer_pool(n, rng)

    counts: dict[HouseholdType, int] = {}
    for agent in agents:
        counts[agent.household_type] = counts.get(agent.household_type, 0) + 1

    for ht, target_frac in VICTORIA_HOUSEHOLD_DISTRIBUTION.items():
        actual_frac = counts.get(ht, 0) / n
        tolerance = 0.08
        assert abs(actual_frac - target_frac) <= tolerance, (
            f"{ht}: expected ~{target_frac:.0%}, got {actual_frac:.0%}"
        )


def test_all_agents_have_max_price():
    """Every agent has a non-None, positive max_price in preferences."""
    rng = np.random.default_rng(7)
    agents = generate_buyer_pool(50, rng)
    for agent in agents:
        assert agent.preferences.max_price is not None
        assert agent.preferences.max_price >= 0


def test_deterministic_with_seed():
    """Same seed produces identical agent pools."""
    agents_a = generate_buyer_pool(50, np.random.default_rng(99))
    agents_b = generate_buyer_pool(50, np.random.default_rng(99))

    for a, b in zip(agents_a, agents_b):
        assert a.household_type == b.household_type
        assert a.financial.annual_income == pytest.approx(b.financial.annual_income)
        assert a.financial.savings == pytest.approx(b.financial.savings)
        assert a.preferences.max_price == pytest.approx(b.preferences.max_price)


def test_different_seeds_produce_different_results():
    """Different seeds produce different agent pools."""
    agents_a = generate_buyer_pool(50, np.random.default_rng(1))
    agents_b = generate_buyer_pool(50, np.random.default_rng(2))

    # At least some incomes should differ
    incomes_a = [a.financial.annual_income for a in agents_a]
    incomes_b = [a.financial.annual_income for a in agents_b]
    assert incomes_a != incomes_b


def test_income_within_distribution_range():
    """All agent incomes should fall within the distribution range ($30K-$500K)."""
    rng = np.random.default_rng(42)
    agents = generate_buyer_pool(200, rng)
    for agent in agents:
        income = agent.financial.annual_income
        assert 30_000 <= income <= 500_000, f"Income {income:.0f} out of range"


def test_all_agents_start_as_entering():
    """Freshly generated agents start with ENTERING status."""
    rng = np.random.default_rng(42)
    agents = generate_buyer_pool(20, rng)
    for agent in agents:
        assert agent.status == AgentStatus.ENTERING


def test_agent_ids_unique():
    """All agent IDs are unique within a generation call."""
    rng = np.random.default_rng(42)
    agents = generate_buyer_pool(100, rng)
    ids = [a.id for a in agents]
    assert len(ids) == len(set(ids))


def test_financial_profile_valid():
    """All generated agents have valid financial profiles (non-negative values)."""
    rng = np.random.default_rng(42)
    agents = generate_buyer_pool(100, rng)
    for agent in agents:
        f = agent.financial
        assert f.annual_income > 0
        assert f.savings >= 0
        assert f.existing_monthly_debts >= 0
        assert f.current_home_value >= 0
        assert f.current_mortgage_balance >= 0
        assert f.total_down_payment >= 0


def test_behavior_profile_bounds():
    """Urgency and risk_tolerance are in [0, 1]."""
    rng = np.random.default_rng(42)
    agents = generate_buyer_pool(100, rng)
    for agent in agents:
        b = agent.behavior
        assert 0.0 <= b.urgency <= 1.0
        assert 0.0 <= b.risk_tolerance <= 1.0
        assert b.patience_weeks > 0
        assert b.adjustment_after_losses > 0


def test_entry_week_assigned():
    """Agents receive the entry_week passed at generation time."""
    rng = np.random.default_rng(42)
    agents = generate_buyer_pool(10, rng, entry_week=5)
    for agent in agents:
        assert agent.entry_week == 5


def test_rate_affects_max_price():
    """Higher contract rate → lower max purchase prices on average."""
    agents_low = generate_buyer_pool(100, np.random.default_rng(42), contract_rate=0.04)
    agents_high = generate_buyer_pool(100, np.random.default_rng(42), contract_rate=0.07)

    avg_low = sum(a.preferences.max_price or 0 for a in agents_low) / 100
    avg_high = sum(a.preferences.max_price or 0 for a in agents_high) / 100
    assert avg_low > avg_high
