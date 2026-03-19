"""
Generate a deterministic 200-property sample dataset for Victoria, BC.

Usage::

    source .venv/bin/activate
    python scripts/generate_sample_data.py

Output: data/properties/sample_victoria_200.json

The output is fully deterministic given the fixed seed (SEED = 7).
Re-running produces identical JSON.

Distribution:
  Oak Bay:       40 properties  ($800K–$2.5M, SFD / condo / townhouse)
  Saanich East:  50 properties  ($500K–$1.4M)
  Langford:      45 properties  ($400K–$1.0M, newer builds)
  View Royal:    30 properties  ($450K–$1.1M)
  Esquimalt:     20 properties  ($400K–$900K, older stock, more condos)
  Colwood:       15 properties  ($450K–$950K, newer subdivisions)

Deliberate test cases (embedded):
  5 properties assessed 20%+ below market value  (folio suffix -UNDER)
  5 properties assessed 20%+ above market value  (folio suffix -OVER)
  10 properties within ±5% of market             (folio suffix -MKT)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

SEED = 7
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "properties" / "sample_victoria_200.json"

# ─── Neighbourhood definitions ────────────────────────────────────────────────

NEIGHBOURHOODS = [
    {
        "neighbourhood": "Oak Bay",
        "municipality": "Oak Bay",
        "lat_base": 48.4284,
        "lon_base": -123.3156,
        "walk_score_range": (70, 90),
        "transit_score_range": (45, 65),
        "school_prox_range": (0.2, 1.5),
        "count": 40,
        "price_range": (800_000, 2_500_000),
        "type_weights": [0.55, 0.20, 0.25, 0.0, 0.0],  # SFD, TOWN, CONDO, DUPLEX, MFD
        "condition_weights": [0.05, 0.15, 0.30, 0.35, 0.15],  # POOR..EXCELLENT
        "year_range": (1940, 2005),
        "lot_range": (5_000, 12_000),
        "area_range": (1_400, 3_500),
        "folio_prefix": "OB",
    },
    {
        "neighbourhood": "Saanich East",
        "municipality": "Saanich",
        "lat_base": 48.4860,
        "lon_base": -123.3600,
        "walk_score_range": (55, 75),
        "transit_score_range": (40, 60),
        "school_prox_range": (0.3, 2.0),
        "count": 50,
        "price_range": (500_000, 1_400_000),
        "type_weights": [0.45, 0.25, 0.30, 0.0, 0.0],
        "condition_weights": [0.05, 0.20, 0.35, 0.30, 0.10],
        "year_range": (1955, 2010),
        "lot_range": (4_500, 9_000),
        "area_range": (1_100, 2_800),
        "folio_prefix": "SE",
    },
    {
        "neighbourhood": "Langford",
        "municipality": "Langford",
        "lat_base": 48.4448,
        "lon_base": -123.5050,
        "walk_score_range": (40, 65),
        "transit_score_range": (30, 55),
        "school_prox_range": (0.5, 3.0),
        "count": 45,
        "price_range": (400_000, 1_000_000),
        "type_weights": [0.35, 0.35, 0.20, 0.05, 0.05],
        "condition_weights": [0.02, 0.08, 0.20, 0.45, 0.25],  # Newer builds → better condition
        "year_range": (1995, 2023),
        "lot_range": (3_500, 7_000),
        "area_range": (1_000, 2_400),
        "folio_prefix": "LF",
    },
    {
        "neighbourhood": "View Royal",
        "municipality": "View Royal",
        "lat_base": 48.4530,
        "lon_base": -123.4330,
        "walk_score_range": (35, 60),
        "transit_score_range": (30, 50),
        "school_prox_range": (0.5, 2.5),
        "count": 30,
        "price_range": (450_000, 1_100_000),
        "type_weights": [0.50, 0.25, 0.20, 0.05, 0.0],
        "condition_weights": [0.05, 0.20, 0.35, 0.30, 0.10],
        "year_range": (1965, 2015),
        "lot_range": (4_000, 8_500),
        "area_range": (1_100, 2_600),
        "folio_prefix": "VR",
    },
    {
        "neighbourhood": "Esquimalt",
        "municipality": "Esquimalt",
        "lat_base": 48.4330,
        "lon_base": -123.4170,
        "walk_score_range": (60, 80),
        "transit_score_range": (50, 70),
        "school_prox_range": (0.2, 1.2),
        "count": 20,
        "price_range": (400_000, 900_000),
        "type_weights": [0.20, 0.20, 0.55, 0.05, 0.0],  # More condos, older stock
        "condition_weights": [0.10, 0.30, 0.35, 0.20, 0.05],
        "year_range": (1945, 2000),
        "lot_range": (3_000, 6_000),
        "area_range": (700, 1_800),
        "folio_prefix": "EQ",
    },
    {
        "neighbourhood": "Colwood",
        "municipality": "Colwood",
        "lat_base": 48.4280,
        "lon_base": -123.4950,
        "walk_score_range": (30, 55),
        "transit_score_range": (25, 45),
        "school_prox_range": (0.8, 3.5),
        "count": 15,
        "price_range": (450_000, 950_000),
        "type_weights": [0.40, 0.35, 0.20, 0.05, 0.0],  # Newer subdivisions
        "condition_weights": [0.02, 0.08, 0.20, 0.45, 0.25],
        "year_range": (2000, 2023),
        "lot_range": (3_500, 7_500),
        "area_range": (1_100, 2_500),
        "folio_prefix": "CW",
    },
]

PROPERTY_TYPES = ["single_family_detached", "townhouse", "condo", "duplex", "manufactured"]
CONDITIONS = ["poor", "fair", "average", "good", "excellent"]


def _round_price(p: float) -> int:
    """Round to nearest $1,000."""
    return int(round(p / 1_000) * 1_000)


def _bedrooms_for_type_and_area(prop_type: str, area: float, rng: np.random.Generator) -> int:
    if prop_type == "condo":
        if area < 800:
            return int(rng.integers(1, 2))
        elif area < 1_200:
            return int(rng.integers(1, 3))
        else:
            return int(rng.integers(2, 4))
    elif prop_type == "single_family_detached":
        if area < 1_500:
            return int(rng.integers(2, 4))
        elif area < 2_200:
            return int(rng.integers(3, 5))
        else:
            return int(rng.integers(4, 6))
    else:  # townhouse, duplex, manufactured
        if area < 1_200:
            return int(rng.integers(2, 3))
        elif area < 1_800:
            return int(rng.integers(2, 4))
        else:
            return int(rng.integers(3, 5))


def _bathrooms_for_bedrooms(beds: int, rng: np.random.Generator) -> float:
    base = max(1.0, beds - 1)
    half = rng.random() < 0.4
    return base + (0.5 if half else 0.0)


def _generate_property(
    folio_id: str,
    nbhd: dict,
    rng: np.random.Generator,
    assessed_value: float | None = None,
) -> dict:
    """Generate one property dict from a neighbourhood template."""
    prop_type_idx = int(rng.choice(5, p=nbhd["type_weights"]))
    prop_type = PROPERTY_TYPES[prop_type_idx]

    cond_idx = int(rng.choice(5, p=nbhd["condition_weights"]))
    condition = CONDITIONS[cond_idx]

    year = int(rng.integers(nbhd["year_range"][0], nbhd["year_range"][1]))

    area = float(rng.uniform(nbhd["area_range"][0], nbhd["area_range"][1]))
    area = round(area / 10) * 10  # Round to nearest 10 sq ft

    if prop_type in ("condo", "manufactured"):
        lot = 0
    else:
        lot = int(rng.uniform(nbhd["lot_range"][0], nbhd["lot_range"][1]))
        lot = round(lot / 100) * 100

    beds = _bedrooms_for_type_and_area(prop_type, area, rng)
    baths = _bathrooms_for_bedrooms(beds, rng)

    if assessed_value is None:
        raw_price = rng.uniform(nbhd["price_range"][0], nbhd["price_range"][1])
        assessed_value = _round_price(raw_price)

    # Taxes approx 0.35% of assessed value
    taxes = _round_price(assessed_value * 0.0035)

    # Features
    has_view = rng.random() < (0.25 if nbhd["neighbourhood"] == "Oak Bay" else 0.10)
    has_waterfront = rng.random() < 0.03
    has_suite = rng.random() < (0.30 if prop_type == "single_family_detached" else 0.05)
    has_garage = rng.random() < (0.70 if prop_type in ("single_family_detached", "townhouse") else 0.20)
    has_corner = rng.random() < 0.15
    has_fireplace = rng.random() < (0.60 if year < 2000 else 0.30)
    has_pool = rng.random() < 0.04
    renovated = rng.random() < (0.20 if year < 1990 else 0.10)

    lat_jitter = rng.uniform(-0.02, 0.02)
    lon_jitter = rng.uniform(-0.02, 0.02)

    walk = int(rng.uniform(nbhd["walk_score_range"][0], nbhd["walk_score_range"][1]))
    transit = int(rng.uniform(nbhd["transit_score_range"][0], nbhd["transit_score_range"][1]))
    school_prox = round(float(rng.uniform(nbhd["school_prox_range"][0], nbhd["school_prox_range"][1])), 1)

    return {
        "folio_id": folio_id,
        "property_type": prop_type,
        "assessed_value": assessed_value,
        "bedrooms": beds,
        "bathrooms": baths,
        "floor_area": area,
        "lot_size": lot,
        "year_built": year,
        "condition": condition,
        "location": {
            "neighbourhood": nbhd["neighbourhood"],
            "municipality": nbhd["municipality"],
            "latitude": round(nbhd["lat_base"] + lat_jitter, 4),
            "longitude": round(nbhd["lon_base"] + lon_jitter, 4),
            "walk_score": walk,
            "transit_score": transit,
            "school_proximity": school_prox,
        },
        "features": {
            "view": bool(has_view),
            "waterfront": bool(has_waterfront),
            "suite": bool(has_suite),
            "garage": bool(has_garage),
            "corner_lot": bool(has_corner),
            "fireplace": bool(has_fireplace),
            "pool": bool(has_pool),
            "renovated_recent": bool(renovated),
        },
        "annual_taxes": taxes,
    }


def generate_properties(seed: int = SEED) -> list[dict]:
    rng = np.random.default_rng(seed)
    properties: list[dict] = []

    # ── Regular properties ─────────────────────────────────────────────────────
    for nbhd in NEIGHBOURHOODS:
        prefix = nbhd["folio_prefix"]
        for i in range(nbhd["count"]):
            folio = f"{prefix}-{i + 1:03d}"
            prop = _generate_property(folio, nbhd, rng)
            properties.append(prop)

    # ── Deliberate test cases ──────────────────────────────────────────────────
    # 5 under-assessed: assessed value set 25% below a plausible market price
    # The simulation should generate bidding wars and high gap_pct on these.
    under_nbhds = [
        NEIGHBOURHOODS[0],  # Oak Bay
        NEIGHBOURHOODS[1],  # Saanich East
        NEIGHBOURHOODS[2],  # Langford
        NEIGHBOURHOODS[3],  # View Royal
        NEIGHBOURHOODS[4],  # Esquimalt
    ]
    for idx, nbhd in enumerate(under_nbhds):
        market_price = int(rng.uniform(
            nbhd["price_range"][0] * 0.6 + nbhd["price_range"][1] * 0.2,
            nbhd["price_range"][0] * 0.2 + nbhd["price_range"][1] * 0.8,
        ))
        # Assessed at 75% of expected market → ~25% below
        assessed = _round_price(market_price * 0.75)
        folio = f"{nbhd['folio_prefix']}-U{idx + 1:02d}-UNDER"
        prop = _generate_property(folio, nbhd, rng, assessed_value=assessed)
        # Force good condition so agents want it
        prop["condition"] = "good"
        properties.append(prop)

    # 5 over-assessed: assessed value set 25% above a plausible market price
    over_nbhds = [
        NEIGHBOURHOODS[0],  # Oak Bay
        NEIGHBOURHOODS[1],  # Saanich East
        NEIGHBOURHOODS[2],  # Langford
        NEIGHBOURHOODS[3],  # View Royal
        NEIGHBOURHOODS[5],  # Colwood
    ]
    for idx, nbhd in enumerate(over_nbhds):
        market_price = int(rng.uniform(
            nbhd["price_range"][0] * 0.4 + nbhd["price_range"][1] * 0.1,
            nbhd["price_range"][0] * 0.1 + nbhd["price_range"][1] * 0.5,
        ))
        # Assessed at 130% of expected market → ~30% above
        assessed = _round_price(market_price * 1.30)
        folio = f"{nbhd['folio_prefix']}-O{idx + 1:02d}-OVER"
        prop = _generate_property(folio, nbhd, rng, assessed_value=assessed)
        # Force poor-to-fair condition so agents don't want it
        prop["condition"] = "fair"
        properties.append(prop)

    # 10 at-market: assessed value within ±5% of generated price
    mkt_nbhds = [
        NEIGHBOURHOODS[0],
        NEIGHBOURHOODS[0],
        NEIGHBOURHOODS[1],
        NEIGHBOURHOODS[1],
        NEIGHBOURHOODS[2],
        NEIGHBOURHOODS[2],
        NEIGHBOURHOODS[3],
        NEIGHBOURHOODS[3],
        NEIGHBOURHOODS[4],
        NEIGHBOURHOODS[5],
    ]
    for idx, nbhd in enumerate(mkt_nbhds):
        market_price = int(rng.uniform(
            nbhd["price_range"][0] * 0.3 + nbhd["price_range"][1] * 0.2,
            nbhd["price_range"][0] * 0.1 + nbhd["price_range"][1] * 0.7,
        ))
        # ±3% jitter → within ±5% of market
        jitter = rng.uniform(-0.03, 0.03)
        assessed = _round_price(market_price * (1 + jitter))
        folio = f"{nbhd['folio_prefix']}-M{idx + 1:02d}-MKT"
        prop = _generate_property(folio, nbhd, rng, assessed_value=assessed)
        prop["condition"] = "average"
        properties.append(prop)

    return properties


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    properties = generate_properties(SEED)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(properties, f, indent=2)
    print(f"Generated {len(properties)} properties → {OUTPUT_PATH}")

    # Summary by neighbourhood
    from collections import Counter
    counts: Counter = Counter(p["location"]["neighbourhood"] for p in properties)
    for nbhd, count in sorted(counts.items()):
        print(f"  {nbhd}: {count}")


if __name__ == "__main__":
    main()
