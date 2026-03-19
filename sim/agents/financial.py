"""
Canadian mortgage qualification calculator.

Implements OSFI B-20 stress test rules, CMHC insurance thresholds,
GDS/TDS ratio limits, and amortization calculations.

Key rules encoded here:
- Semi-annual compounding (not monthly) per Canadian convention
- Stress test: qualify at max(contract_rate + 2%, 5.25%)
- GDS limit: 32% of gross monthly income
- TDS limit: 40% of gross monthly income
- CMHC insurance required if down payment < 20%
- Minimum down payment scaled by purchase price tier

All rates are annual. All amounts in CAD.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sim.agents.models import FinancialProfile

# --- Constants ---
GDS_LIMIT = 0.32              # Gross Debt Service ratio limit
TDS_LIMIT = 0.40              # Total Debt Service ratio limit
STRESS_TEST_FLOOR = 0.0525    # Minimum qualifying rate (5.25%)
STRESS_TEST_BUFFER = 0.02     # Contract rate + 2%
PROPERTY_TAX_RATE = 0.004     # Approx 0.4% of value annually (Victoria avg)
MONTHLY_HEAT = 175.0          # Standard heating cost estimate (CMHC guideline)
CMHC_THRESHOLD = 0.20         # 20% down = no insurance needed

# CMHC insurance premiums (% of mortgage, by down payment percentage band)
CMHC_PREMIUMS: dict[tuple[float, float], float] = {
    (0.05, 0.0999): 0.0400,   # 5-9.99% down → 4.00% premium
    (0.10, 0.1499): 0.0310,   # 10-14.99% → 3.10%
    (0.15, 0.1999): 0.0280,   # 15-19.99% → 2.80%
}


def calculate_stress_test_rate(contract_rate: float) -> float:
    """Qualifying rate = max(contract_rate + 2%, 5.25%)."""
    return max(contract_rate + STRESS_TEST_BUFFER, STRESS_TEST_FLOOR)


def calculate_monthly_payment(
    principal: float,
    annual_rate: float,
    amortization_years: int = 25,
) -> float:
    """
    Monthly mortgage payment using Canadian semi-annual compounding.

    Canadian mortgages compound semi-annually, not monthly (Interest Act).
    Effective monthly rate = (1 + annual_rate/2)^(1/6) - 1
    """
    if annual_rate <= 0 or principal <= 0:
        return 0.0
    semi_annual = annual_rate / 2
    monthly_rate = (1 + semi_annual) ** (1 / 6) - 1
    n = amortization_years * 12
    payment = principal * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
    return payment


def calculate_cmhc_premium(purchase_price: float, down_payment: float) -> float:
    """
    CMHC mortgage insurance premium.

    Returns 0 if down payment >= 20% of purchase price.
    Otherwise returns the premium amount (added to the mortgage).
    """
    if purchase_price <= 0:
        return 0.0
    dp_pct = down_payment / purchase_price
    if dp_pct >= CMHC_THRESHOLD:
        return 0.0
    for (low, high), premium_rate in CMHC_PREMIUMS.items():
        if low <= dp_pct <= high:
            mortgage = purchase_price - down_payment
            return mortgage * premium_rate
    return 0.0


def calculate_max_purchase_price(
    annual_income: float,
    down_payment: float,
    monthly_debts: float = 0.0,
    contract_rate: float = 0.05,
    property_tax_rate: float = PROPERTY_TAX_RATE,
    amortization_years: int = 25,
) -> float:
    """
    Maximum purchase price given income, down payment, and debts.

    Uses GDS and TDS constraints at the stress test qualifying rate.
    Binary search over mortgage amount; returns purchase price (mortgage + down).

    CMHC premium is accounted for by reducing max purchase price when
    insurance would be triggered (premium is added to mortgage, eating
    into qualification room).
    """
    if annual_income <= 0:
        return 0.0

    qualifying_rate = calculate_stress_test_rate(contract_rate)
    gross_monthly = annual_income / 12

    # Binary search bounds: mortgage only (purchase = mortgage + down_payment)
    low, high = 0.0, annual_income * 8  # 8× income is a safe upper bound

    for _ in range(50):  # 50 iterations gives sub-dollar precision
        mid = (low + high) / 2
        purchase_price = mid + down_payment

        monthly_payment = calculate_monthly_payment(mid, qualifying_rate, amortization_years)
        monthly_tax = purchase_price * property_tax_rate / 12

        gds = (monthly_payment + monthly_tax + MONTHLY_HEAT) / gross_monthly
        tds = (monthly_payment + monthly_tax + MONTHLY_HEAT + monthly_debts) / gross_monthly

        if gds <= GDS_LIMIT and tds <= TDS_LIMIT:
            low = mid
        else:
            high = mid

    max_mortgage = low
    purchase_price = max_mortgage + down_payment

    # Reduce for CMHC premium (premium is added to mortgage, consuming qualification room)
    cmhc = calculate_cmhc_premium(purchase_price, down_payment)
    if cmhc > 0:
        purchase_price -= cmhc

    return max(0.0, purchase_price)


def qualifies_for_property(
    agent_financial: "FinancialProfile",
    property_price: float,
    contract_rate: float = 0.05,
) -> tuple[bool, str]:
    """
    Check if an agent can qualify to purchase at the given price.

    Returns (qualified: bool, reason: str).
    Reason is "qualified" or describes why not (for logging/debugging).

    Enforces Canadian minimum down payment rules:
    - Up to $500K: 5% minimum
    - $500K–$1M: 5% on first $500K + 10% on remainder
    - Over $1M: 20% minimum (CMHC unavailable over $1M)
    """
    down = agent_financial.total_down_payment

    # Canadian minimum down payment rules
    if property_price <= 500_000:
        min_down = property_price * 0.05
    elif property_price <= 1_000_000:
        min_down = 500_000 * 0.05 + (property_price - 500_000) * 0.10
    else:
        min_down = property_price * 0.20

    if down < min_down:
        return False, (
            f"insufficient_down_payment (need ${min_down:,.0f}, have ${down:,.0f})"
        )

    max_price = calculate_max_purchase_price(
        annual_income=agent_financial.annual_income,
        down_payment=down,
        monthly_debts=agent_financial.existing_monthly_debts,
        contract_rate=contract_rate,
    )

    if property_price > max_price:
        return False, f"exceeds_max_qualification (max ${max_price:,.0f})"

    return True, "qualified"
