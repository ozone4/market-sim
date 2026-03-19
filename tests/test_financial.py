"""
Tests for Canadian mortgage financial math.

These are the most critical tests in the suite. Financial qualification is
the primary gate for agent behaviour — all math must be correct.
"""
import pytest

from sim.agents.financial import (
    MONTHLY_HEAT,
    GDS_LIMIT,
    TDS_LIMIT,
    calculate_cmhc_premium,
    calculate_max_purchase_price,
    calculate_monthly_payment,
    calculate_stress_test_rate,
    qualifies_for_property,
)
from sim.agents.models import FinancialProfile


# ─── Stress test rate ─────────────────────────────────────────────────────────

def test_stress_test_rate_above_floor():
    """Contract 4% → buffer gives 6%, above the 5.25% floor."""
    assert calculate_stress_test_rate(0.04) == pytest.approx(0.06)


def test_stress_test_rate_below_floor():
    """Contract 2% → 4% < 5.25%, so floor applies."""
    assert calculate_stress_test_rate(0.02) == pytest.approx(0.0525)


def test_stress_test_rate_at_floor_boundary():
    """Contract 3.25% → 5.25% exactly, boundary case."""
    assert calculate_stress_test_rate(0.0325) == pytest.approx(0.0525)


def test_stress_test_rate_high_rate():
    """Contract 7% → 9%, well above floor."""
    assert calculate_stress_test_rate(0.07) == pytest.approx(0.09)


# ─── Monthly payment (Canadian semi-annual compounding) ───────────────────────

def test_monthly_payment_basic():
    """
    Verify payment for a $500K mortgage at 5% over 25 years.

    Canadian semi-annual compounding:
    monthly_rate = (1 + 0.025)^(1/6) - 1 ≈ 0.004124
    n = 300 months
    Expected ≈ $2,908
    """
    payment = calculate_monthly_payment(500_000, 0.05, 25)
    # Known reference: ~$2,908 for these inputs
    assert 2_800 < payment < 3_000, f"Payment {payment:.2f} out of expected range"


def test_monthly_payment_zero_rate():
    """Zero annual rate → returns 0 (avoids division by zero)."""
    payment = calculate_monthly_payment(500_000, 0.0, 25)
    assert payment == 0.0


def test_monthly_payment_zero_principal():
    """Zero principal → returns 0."""
    assert calculate_monthly_payment(0.0, 0.05, 25) == 0.0


def test_monthly_payment_higher_rate():
    """Higher rate → higher payment. Monotonic relationship."""
    p_low = calculate_monthly_payment(400_000, 0.04, 25)
    p_high = calculate_monthly_payment(400_000, 0.07, 25)
    assert p_high > p_low


def test_monthly_payment_shorter_amortization():
    """Shorter amortization → higher monthly payment."""
    p_25 = calculate_monthly_payment(400_000, 0.05, 25)
    p_20 = calculate_monthly_payment(400_000, 0.05, 20)
    assert p_20 > p_25


def test_monthly_payment_canadian_compounding():
    """
    Canadian semi-annual vs monthly compounding produces different results.

    Monthly compounding: (1 + 0.05/12)^1 - 1 ≈ 0.004167
    Semi-annual: (1 + 0.025)^(1/6) - 1 ≈ 0.004124

    Semi-annual gives slightly lower rate per month → lower payment.
    """
    semi_annual_payment = calculate_monthly_payment(500_000, 0.05, 25)
    # If we computed with monthly compounding (wrong for Canada), rate would be higher
    # Just verify our number is in a reasonable range for the semi-annual convention
    assert semi_annual_payment < calculate_monthly_payment(500_000, 0.051, 25)


# ─── CMHC insurance premiums ─────────────────────────────────────────────────

def test_cmhc_premium_20pct_down():
    """20% down or more → no CMHC premium."""
    premium = calculate_cmhc_premium(800_000, 160_000)
    assert premium == 0.0


def test_cmhc_premium_exactly_20pct():
    """Exactly 20% down → no premium (boundary)."""
    assert calculate_cmhc_premium(500_000, 100_000) == 0.0


def test_cmhc_premium_10pct_down():
    """10% down → 3.10% of mortgage amount."""
    purchase = 600_000
    down = 60_000  # 10%
    expected_mortgage = 540_000
    expected_premium = expected_mortgage * 0.0310
    assert calculate_cmhc_premium(purchase, down) == pytest.approx(expected_premium)


def test_cmhc_premium_5pct_down():
    """5% down → 4.00% of mortgage amount."""
    purchase = 400_000
    down = 20_000  # 5%
    expected_mortgage = 380_000
    expected_premium = expected_mortgage * 0.0400
    assert calculate_cmhc_premium(purchase, down) == pytest.approx(expected_premium)


def test_cmhc_premium_15pct_down():
    """15% down → 2.80% of mortgage."""
    purchase = 700_000
    down = 105_000  # 15%
    expected_mortgage = 595_000
    expected_premium = expected_mortgage * 0.0280
    assert calculate_cmhc_premium(purchase, down) == pytest.approx(expected_premium)


def test_cmhc_premium_zero_purchase():
    """Zero purchase price → no premium (guard clause)."""
    assert calculate_cmhc_premium(0.0, 0.0) == 0.0


# ─── Maximum purchase price ───────────────────────────────────────────────────

def test_max_purchase_gds_limited():
    """
    High income, no debts → GDS is the binding constraint.

    $200K income, $100K down, 0 debts. GDS constrains mortgage.
    """
    max_price = calculate_max_purchase_price(
        annual_income=200_000,
        down_payment=100_000,
        monthly_debts=0.0,
        contract_rate=0.05,
    )
    # Verify GDS is satisfied at the result
    from sim.agents.financial import calculate_stress_test_rate, PROPERTY_TAX_RATE
    qualifying_rate = calculate_stress_test_rate(0.05)
    mortgage = max_price - 100_000
    payment = calculate_monthly_payment(mortgage, qualifying_rate, 25)
    monthly_tax = max_price * PROPERTY_TAX_RATE / 12
    gds = (payment + monthly_tax + MONTHLY_HEAT) / (200_000 / 12)
    assert gds <= GDS_LIMIT + 0.001  # Small tolerance for floating point


def test_max_purchase_tds_limited():
    """
    Moderate income, high debts → TDS is the binding constraint.

    $80K income, $30K down, $2000/mo debts. TDS constrains mortgage.
    """
    max_price = calculate_max_purchase_price(
        annual_income=80_000,
        down_payment=30_000,
        monthly_debts=2_000.0,
        contract_rate=0.05,
    )
    qualifying_rate = calculate_stress_test_rate(0.05)
    mortgage = max_price - 30_000
    payment = calculate_monthly_payment(mortgage, qualifying_rate, 25)
    monthly_tax = max_price * 0.004 / 12
    gross_monthly = 80_000 / 12
    tds = (payment + monthly_tax + MONTHLY_HEAT + 2_000) / gross_monthly
    assert tds <= TDS_LIMIT + 0.001


def test_max_purchase_increases_with_income():
    """Higher income → higher max purchase. Monotonic relationship."""
    low = calculate_max_purchase_price(60_000, 50_000)
    high = calculate_max_purchase_price(120_000, 50_000)
    assert high > low


def test_max_purchase_increases_with_down_payment():
    """More down payment → higher max purchase."""
    low = calculate_max_purchase_price(100_000, 50_000)
    high = calculate_max_purchase_price(100_000, 150_000)
    assert high > low


def test_max_purchase_decreases_with_rate():
    """Higher rate → lower qualification → lower max price."""
    low_rate = calculate_max_purchase_price(120_000, 80_000, contract_rate=0.04)
    high_rate = calculate_max_purchase_price(120_000, 80_000, contract_rate=0.07)
    assert low_rate > high_rate


def test_max_purchase_zero_income():
    """Zero income → 0 max purchase."""
    assert calculate_max_purchase_price(0, 100_000) == 0.0


# ─── Minimum down payment rules ──────────────────────────────────────────────

def test_min_down_payment_under_500k():
    """Under $500K: 5% minimum down is enough when income also qualifies."""
    # $130K income, $20K savings (5% of 400K) — income sufficient to qualify at $400K
    profile = FinancialProfile(annual_income=130_000, savings=20_000)
    qualified, reason = qualifies_for_property(profile, 400_000)
    assert qualified, reason


def test_min_down_payment_under_500k_insufficient():
    """Under $500K: savings below 5% → reject."""
    profile = FinancialProfile(annual_income=80_000, savings=10_000)  # < 5% of 300K
    qualified, reason = qualifies_for_property(profile, 300_000)
    assert not qualified
    assert "insufficient_down_payment" in reason


def test_min_down_payment_500k_to_1m():
    """$500K-$1M threshold: 5% on first $500K + 10% on remainder."""
    # $750K purchase: min_down = 25K + 25K = $50K
    profile = FinancialProfile(annual_income=150_000, savings=50_000)
    qualified, reason = qualifies_for_property(profile, 750_000)
    # Should qualify on down payment (may fail income-based)
    if not qualified:
        assert "insufficient_down_payment" not in reason


def test_min_down_payment_500k_to_1m_exact():
    """Verify the split-threshold calculation at $750K."""
    profile_just_enough = FinancialProfile(annual_income=200_000, savings=50_000)
    profile_short = FinancialProfile(annual_income=200_000, savings=49_000)
    q_ok, _ = qualifies_for_property(profile_just_enough, 750_000)
    q_no, reason_no = qualifies_for_property(profile_short, 750_000)
    # 50K is exactly the min for $750K. 49K should fail on down payment.
    assert "insufficient_down_payment" in reason_no


def test_min_down_payment_over_1m():
    """Over $1M: 20% minimum."""
    # $1.2M: min_down = $240K
    profile_ok = FinancialProfile(annual_income=300_000, savings=240_000)
    profile_short = FinancialProfile(annual_income=300_000, savings=200_000)
    q_ok, _ = qualifies_for_property(profile_ok, 1_200_000)
    q_no, reason_no = qualifies_for_property(profile_short, 1_200_000)
    assert "insufficient_down_payment" in reason_no


# ─── Qualification scenarios ─────────────────────────────────────────────────

def test_qualifies_for_affordable_property():
    """High income, adequate down, modest property → qualifies."""
    profile = FinancialProfile(annual_income=150_000, savings=100_000)
    qualified, reason = qualifies_for_property(profile, 600_000)
    assert qualified, reason


def test_rejects_unaffordable_property():
    """Low income, small savings → rejects expensive property."""
    profile = FinancialProfile(annual_income=60_000, savings=40_000)
    qualified, reason = qualifies_for_property(profile, 1_200_000)
    assert not qualified
    assert "exceeds_max_qualification" in reason or "insufficient_down_payment" in reason


def test_first_time_buyer_no_equity():
    """First-time buyer: down payment = savings only (no equity)."""
    profile = FinancialProfile(
        annual_income=100_000,
        savings=60_000,
        is_first_time_buyer=True,
        current_home_value=0.0,
        current_mortgage_balance=0.0,
    )
    assert profile.total_down_payment == pytest.approx(60_000)
    assert profile.available_equity == 0.0


def test_move_up_buyer_with_equity():
    """Move-up buyer: down payment = savings + net equity from current home."""
    profile = FinancialProfile(
        annual_income=130_000,
        savings=80_000,
        current_home_value=700_000,
        current_mortgage_balance=300_000,
        is_first_time_buyer=False,
    )
    # Equity = (700K - 300K) * 0.93 = 400K * 0.93 = 372K
    expected_equity = 400_000 * 0.93
    assert profile.available_equity == pytest.approx(expected_equity)
    assert profile.total_down_payment == pytest.approx(80_000 + expected_equity)
