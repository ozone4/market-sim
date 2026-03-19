# API Reference

Base URL: `http://localhost:8000`

All responses include a `disclaimer` field. All monetary values are in CAD.

---

## GET /api/health

Liveness check.

**Response**
```json
{
  "status": "ok",
  "version": "0.3.0",
  "tests_passing": 122
}
```

---

## POST /api/analyze

Run a single simulation and return assessment gap analysis.

**Request Body**
```json
{
  "properties": [
    {
      "folio_id": "OB-001",
      "property_type": "single_family_detached",
      "assessed_value": 1850000,
      "bedrooms": 4,
      "bathrooms": 3.0,
      "floor_area": 2800,
      "lot_size": 7500,
      "year_built": 1962,
      "condition": "excellent",
      "location": {
        "neighbourhood": "Oak Bay",
        "municipality": "Oak Bay",
        "walk_score": 72,
        "transit_score": 55,
        "school_proximity": 0.3
      },
      "features": {
        "view": false,
        "waterfront": false,
        "suite": true,
        "garage": true,
        "renovated_recent": true
      },
      "annual_taxes": 9200
    }
  ],
  "config": {
    "num_agents": 500,
    "num_weeks": 26,
    "contract_rate": 0.05,
    "seed": 42,
    "initial_markup": 0.03,
    "markup_variance": 0.05,
    "agent_entry_mode": "front_loaded",
    "replenishment_rate": 0.0,
    "replenishment_variance": 0.02
  }
}
```

**Response**
```json
{
  "run_date": "2026-03-18",
  "config_summary": { "num_agents": 500, "num_weeks": 26, "seed": 42, "..." : "..." },
  "property_results": [
    {
      "folio_id": "OB-001",
      "assessed_value": 1850000,
      "simulated_clearing_price": 2020000,
      "gap_pct": 9.19,
      "gap_signal": "under_assessed",
      "confidence": "high",
      "market_pressure_score": 7.0,
      "days_on_market": 14,
      "offer_count": 4,
      "rounds": 2,
      "review_recommendation": "within_norms"
    }
  ],
  "neighbourhood_summaries": [
    {
      "neighbourhood": "Oak Bay",
      "municipality": "Oak Bay",
      "property_count": 1,
      "avg_gap_pct": 9.19,
      "median_gap_pct": 9.19,
      "under_assessed_count": 1,
      "over_assessed_count": 0,
      "within_tolerance_count": 0,
      "avg_market_pressure": 7.0,
      "avg_dom": 14.0,
      "systemic_signal": "systemic_under",
      "flagged_for_review": 0
    }
  ],
  "stability_results": null,
  "total_properties": 1,
  "total_sold": 1,
  "total_unsold": 0,
  "flagged_for_review": 0,
  "systemic_signals": ["Oak Bay"],
  "disclaimer": "This analysis is based on simulated market behavior..."
}
```

**Gap signal values**
| Value | Meaning |
|-------|---------|
| `within_tolerance` | \|gap_pct\| ≤ 8% |
| `under_assessed` | gap_pct > 8% (market pays more) |
| `over_assessed` | gap_pct < -8% (market pays less) |

**Review recommendation values**
| Value | Meaning |
|-------|---------|
| `flag_for_review` | \|gap_pct\| > 15% AND confidence ≠ low |
| `data_insufficient` | Property expired unsold OR confidence = low |
| `within_norms` | Everything else |

---

## POST /api/analyze/stable

Run N simulations with different seeds and return gap analysis with stability metrics.

**Request Body** — same as `/api/analyze` plus:
```json
{
  "num_runs": 10
}
```

**Additional response field** — `stability_results`:
```json
{
  "stability_results": {
    "OB-001": {
      "folio_id": "OB-001",
      "num_runs": 10,
      "clearing_prices": [2020000, 1980000, 2050000, "..."],
      "gap_signals": ["under_assessed", "under_assessed", "within_tolerance", "..."],
      "mean_clearing_price": 2016666.67,
      "std_clearing_price": 35118.85,
      "p10_clearing_price": 1980000,
      "p90_clearing_price": 2050000,
      "dominant_signal": "under_assessed",
      "signal_agreement_pct": 70.0,
      "stability": "moderate"
    }
  }
}
```

**Stability values**
| Value | Meaning |
|-------|---------|
| `stable` | > 80% of runs agree on the dominant signal |
| `moderate` | 60-80% agreement |
| `unstable` | < 60% agreement |

---

## POST /api/simulate

Run the simulation and return raw output without gap analysis (for debugging).

**Request Body** — same as `/api/analyze`

**Response**
```json
{
  "seed": 42,
  "total_weeks": 26,
  "properties_sold": ["OB-001", "SE-002"],
  "properties_unsold": ["LF-003"],
  "transactions": [
    {
      "folio_id": "OB-001",
      "outcome": "sold",
      "final_price": 2020000,
      "rounds": 2,
      "offer_count": 4
    }
  ],
  "disclaimer": "This analysis is based on simulated market behavior..."
}
```

---

## Error Responses

| Status | Meaning |
|--------|---------|
| 422 | Validation error (invalid property data or config) |
| 500 | Internal server error |
