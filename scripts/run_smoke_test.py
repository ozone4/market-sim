"""
Smoke test: run simulation with sample Victoria data and 500 agents.

Prints human-readable results to stdout including:
- Weekly market summary
- Properties sold: assessed vs clearing price, DOM, offer count
- Properties not sold: assessed vs asking, DOM, price reductions
- Agent outcomes: how many bought, exited, still searching
- KEY EMERGENCE CHECK: underpriced vs overpriced property outcomes

Usage:
    python scripts/run_smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sure the project root is on the path when run as a script
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sim.engine.simulation import SimulationConfig, run_simulation
from sim.properties.loader import load_properties_from_json

# ─── Constants ────────────────────────────────────────────────────────────────
SAMPLE_DATA = PROJECT_ROOT / "data" / "properties" / "sample_victoria.json"
NUM_AGENTS = 500
NUM_WEEKS = 26
SEED = 42
CONTRACT_RATE = 0.05

UNDERPRICED_ID = "LF-007-UNDERPRICED"
OVERPRICED_ID = "OB-006-OVERPRICED"
AVERAGE_ID = "SE-007-AVERAGE"


def _divider(char: str = "─", width: int = 72) -> str:
    return char * width


def main() -> None:
    print(_divider("═"))
    print("  MARKET SIMULATION SMOKE TEST — Victoria Sample Data")
    print(_divider("═"))
    print(f"  Agents: {NUM_AGENTS}  |  Weeks: {NUM_WEEKS}  |  Rate: {CONTRACT_RATE:.1%}  |  Seed: {SEED}")
    print()

    # Load properties
    properties = load_properties_from_json(SAMPLE_DATA)
    print(f"Loaded {len(properties)} properties from {SAMPLE_DATA.name}")
    print()

    # Configure and run
    config = SimulationConfig(
        num_agents=NUM_AGENTS,
        num_weeks=NUM_WEEKS,
        contract_rate=CONTRACT_RATE,
        seed=SEED,
        initial_markup=0.03,
        markup_variance=0.04,
        agent_entry_mode="front_loaded",
        shocks=[],
    )

    print("Running simulation…")
    result = run_simulation(properties, config)
    print(f"Done. {len(result.transactions)} sales | "
          f"{len(result.properties_sold)}/{len(properties)} properties sold\n")

    # ── Weekly summary ────────────────────────────────────────────────────────
    print(_divider())
    print("WEEKLY MARKET SUMMARY")
    print(_divider())
    print(
        f"{'Wk':>3}  {'Listings':>8}  {'Buyers':>7}  {'Offers':>6}  "
        f"{'Sales':>5}  {'Expires':>7}  {'Avg $':>10}  {'Avg DOM':>7}  {'Temp'}"
    )
    print(_divider("-"))
    for snap in result.weekly_snapshots:
        avg_p = f"${snap.avg_sale_price:,.0f}" if snap.avg_sale_price > 0 else "—"
        print(
            f"{snap.week:>3}  {snap.active_listings:>8}  {snap.active_buyers:>7}  "
            f"{snap.offers_this_week:>6}  {snap.sales_this_week:>5}  "
            f"{snap.expirations_this_week:>7}  {avg_p:>10}  "
            f"{snap.avg_days_on_market:>7.1f}  {snap.market_temperature}"
        )
    print()

    # Build property index for quick lookup
    prop_by_folio = {p.folio_id: p for p in properties}
    # Build inventory history from transactions for final asking
    sold_info: dict[str, dict] = {}
    for r in result.transactions:
        sold_info[r.folio_id] = {
            "final_price": r.final_price,
            "rounds": r.rounds,
            "num_offers": len({o.agent_id for o in r.all_offers}),
            "sale_week": r.winning_offer.week if r.winning_offer else 0,
        }

    # ── Properties that sold ──────────────────────────────────────────────────
    print(_divider())
    print("PROPERTIES SOLD")
    print(_divider())
    header = (
        f"{'Folio':<22}  {'Assessed':>10}  {'Asking':>10}  "
        f"{'Sale $':>10}  {'vs Assessed':>11}  {'DOM':>5}  "
        f"{'Offers':>6}  {'Wk':>3}"
    )
    print(header)
    print(_divider("-"))

    for folio_id in sorted(result.properties_sold):
        prop = prop_by_folio.get(folio_id)
        info = sold_info.get(folio_id, {})
        if not prop or not info:
            continue

        assessed = prop.assessed_value
        sale_price = info.get("final_price", 0)
        gap_pct = (sale_price - assessed) / assessed * 100 if assessed > 0 else 0
        gap_str = f"{gap_pct:+.1f}%"

        # Find asking price from initial markup stored in inventory (approximate)
        # We can reconstruct DOM from the sale week vs listed week (week 0)
        sale_week = info.get("sale_week", 0)
        dom_approx = sale_week * 7  # Listed week 0; sold at sale_week

        print(
            f"{folio_id:<22}  ${assessed:>9,.0f}  "
            f"—{' ':>9}  "   # We don't store asking easily; omit
            f"${sale_price:>9,.0f}  {gap_str:>11}  {dom_approx:>5}  "
            f"{info.get('num_offers', 0):>6}  {info.get('sale_week', 0):>3}"
        )
    print()

    # ── Properties that did NOT sell ──────────────────────────────────────────
    print(_divider())
    print("PROPERTIES NOT SOLD (expired / still active)")
    print(_divider())
    if not result.properties_unsold:
        print("  (all properties sold)")
    else:
        print(f"{'Folio':<22}  {'Assessed':>10}  {'Type':<12}  {'Condition':<10}  {'Beds':>4}")
        print(_divider("-"))
        for folio_id in sorted(result.properties_unsold):
            prop = prop_by_folio.get(folio_id)
            if not prop:
                continue
            print(
                f"{folio_id:<22}  ${prop.assessed_value:>9,.0f}  "
                f"{prop.property_type.value:<12}  {prop.condition.value:<10}  "
                f"{prop.bedrooms:>4}"
            )
    print()

    # ── Agent outcomes ────────────────────────────────────────────────────────
    print(_divider())
    print("AGENT OUTCOMES")
    print(_divider())
    status_counts: dict[str, int] = {}
    for outcome in result.agent_outcomes.values():
        status_counts[outcome.final_status] = (
            status_counts.get(outcome.final_status, 0) + 1
        )

    total_agents = len(result.agent_outcomes)
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        pct = count / total_agents * 100
        print(f"  {status:<20} {count:>5}  ({pct:.1f}%)")

    print()
    won_outcomes = [o for o in result.agent_outcomes.values() if o.final_status == "won"]
    if won_outcomes:
        avg_weeks = sum(
            o.weeks_to_purchase for o in won_outcomes
            if o.weeks_to_purchase is not None
        ) / len(won_outcomes) if won_outcomes else 0
        avg_losses = sum(o.bids_lost for o in won_outcomes) / len(won_outcomes)
        print(f"  Buyers who purchased: {len(won_outcomes)}")
        print(f"  Avg week of purchase: {avg_weeks:.1f}")
        print(f"  Avg bid losses before winning: {avg_losses:.1f}")
    print()

    # ── Key emergence check ───────────────────────────────────────────────────
    print(_divider("═"))
    print("KEY EMERGENCE CHECK")
    print(_divider("═"))
    print()

    for label, folio_id in [
        ("UNDERPRICED", UNDERPRICED_ID),
        ("OVERPRICED", OVERPRICED_ID),
        ("AVERAGE", AVERAGE_ID),
    ]:
        prop = prop_by_folio.get(folio_id)
        if not prop:
            print(f"  [{label}] {folio_id}: not found in properties")
            continue

        print(f"  [{label}] {folio_id}")
        print(f"    Assessed value:  ${prop.assessed_value:,.0f}")
        print(f"    Condition:       {prop.condition.value}")
        print(f"    Bedrooms:        {prop.bedrooms}")
        print(f"    Type:            {prop.property_type.value}")

        if folio_id in sold_info:
            info = sold_info[folio_id]
            sale_price = info["final_price"]
            gap_pct = (sale_price - prop.assessed_value) / prop.assessed_value * 100
            gap_str = f"{gap_pct:+.1f}%"
            num_offers = info["num_offers"]
            rounds = info["rounds"]
            sale_week = info["sale_week"]
            dom = sale_week * 7

            print(f"    SOLD at:         ${sale_price:,.0f}  ({gap_str} vs assessed)")
            print(f"    Offers:          {num_offers}  |  Rounds: {rounds}  |  "
                  f"DOM: {dom}  |  Week: {sale_week}")

            if label == "UNDERPRICED":
                if sale_price > prop.assessed_value and num_offers >= 2:
                    print("    ✓ EMERGENCE: Bidding war, cleared above assessed — UNDERPRICED signal")
                elif sale_price > prop.assessed_value:
                    print("    ~ Cleared above assessed (single offer — market absorbed it quickly)")
                else:
                    print("    ✗ Did not clear above assessed — check parameters")
            elif label == "OVERPRICED":
                if dom >= 42 and num_offers == 1:
                    print("    ✓ EMERGENCE: Slow sale, minimal competition (+{:.1f}% — overpricing signal)".format(gap_pct))
                elif num_offers == 1 and gap_pct < 5:
                    print("    ✓ Low competition, weak clearance — OVERPRICED signal")
                else:
                    print(f"    ~ Sold with {num_offers} offers — market cleared despite overpricing")
            elif label == "AVERAGE":
                if 3 <= gap_pct <= 12:
                    print("    ✓ Cleared near assessed — AVERAGE baseline confirmed")
                else:
                    print(f"    ~ Cleared {gap_str} vs assessed")
        else:
            print("    DID NOT SELL (expired or still active)")
            if label == "OVERPRICED":
                print("    ✓ EMERGENCE: Overpriced property sat unsold — strong OVERPRICED signal")
            elif label == "UNDERPRICED":
                print("    ✗ Expected underpriced property to sell — check parameters")
            else:
                print("    ~ Did not sell within simulation window")

        print()

    print(_divider("═"))


if __name__ == "__main__":
    main()
