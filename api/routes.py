"""
FastAPI route handlers for the market simulation API.

Endpoints:
  GET  /api/health           — Liveness check
  POST /api/analyze          — Single-run assessment gap analysis
  POST /api/analyze/stable   — Multi-run stability analysis
  POST /api/simulate         — Raw simulation result (for debugging/exploration)
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AssessmentGapSchema,
    CompareRequest,
    ComparativeReportSchema,
    HealthResponse,
    NeighbourhoodSummarySchema,
    PropertyComparisonSchema,
    ScenarioRequest,
    SimulateRequest,
    SimulateResponse,
    StableAnalyzeRequest,
    StabilityResultSchema,
    TransactionSchema,
)
from sim.analysis.comparative import run_comparative_analysis
from sim.analysis.report import generate_report
from sim.analysis.stability import run_stability_analysis
from sim.engine.simulation import SimulationConfig, run_simulation
from sim.properties.loader import load_properties_from_dict
from sim.scenarios.presets import SCENARIOS, apply_scenario

router = APIRouter(prefix="/api")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _config_from_schema(schema) -> SimulationConfig:
    return SimulationConfig(
        num_agents=schema.num_agents,
        num_weeks=schema.num_weeks,
        contract_rate=schema.contract_rate,
        seed=schema.seed,
        initial_markup=schema.initial_markup,
        markup_variance=schema.markup_variance,
        agent_entry_mode=schema.agent_entry_mode,
        replenishment_rate=schema.replenishment_rate,
        replenishment_variance=schema.replenishment_variance,
    )


def _report_to_response(report) -> AnalyzeResponse:
    """Convert internal AnalysisReport dataclass to API response model."""
    property_results = [
        AssessmentGapSchema(
            folio_id=g.folio_id,
            assessed_value=g.assessed_value,
            simulated_clearing_price=g.simulated_clearing_price,
            gap_pct=g.gap_pct,
            gap_signal=g.gap_signal,
            confidence=g.confidence,
            market_pressure_score=g.market_pressure_score,
            days_on_market=g.days_on_market,
            offer_count=g.offer_count,
            rounds=g.rounds,
            review_recommendation=g.review_recommendation,
        )
        for g in report.property_results
    ]

    neighbourhood_summaries = [
        NeighbourhoodSummarySchema(
            neighbourhood=n.neighbourhood,
            municipality=n.municipality,
            property_count=n.property_count,
            avg_gap_pct=n.avg_gap_pct,
            median_gap_pct=n.median_gap_pct,
            under_assessed_count=n.under_assessed_count,
            over_assessed_count=n.over_assessed_count,
            within_tolerance_count=n.within_tolerance_count,
            avg_market_pressure=n.avg_market_pressure,
            avg_dom=n.avg_dom,
            systemic_signal=n.systemic_signal,
            flagged_for_review=n.flagged_for_review,
        )
        for n in report.neighbourhood_summaries
    ]

    stability_results = None
    if report.stability_results:
        stability_results = {
            fid: StabilityResultSchema(
                folio_id=sr.folio_id,
                num_runs=sr.num_runs,
                clearing_prices=sr.clearing_prices,
                gap_signals=sr.gap_signals,
                mean_clearing_price=sr.mean_clearing_price,
                std_clearing_price=sr.std_clearing_price,
                p10_clearing_price=sr.p10_clearing_price,
                p90_clearing_price=sr.p90_clearing_price,
                dominant_signal=sr.dominant_signal,
                signal_agreement_pct=sr.signal_agreement_pct,
                stability=sr.stability,
            )
            for fid, sr in report.stability_results.items()
        }

    return AnalyzeResponse(
        run_date=report.run_date,
        config_summary=report.config_summary,
        property_results=property_results,
        neighbourhood_summaries=neighbourhood_summaries,
        stability_results=stability_results,
        total_properties=report.total_properties,
        total_sold=report.total_sold,
        total_unsold=report.total_unsold,
        flagged_for_review=report.flagged_for_review,
        systemic_signals=report.systemic_signals,
        disclaimer=report.disclaimer,
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check — returns version and baseline test count."""
    return HealthResponse(status="ok", version="0.3.0", tests_passing=122)


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    Run a single simulation and return assessment gap analysis.

    The response includes property-level gap signals, neighbourhood summaries,
    and aggregate statistics. No stability analysis is performed.
    """
    try:
        properties = load_properties_from_dict(request.properties)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not properties:
        raise HTTPException(status_code=422, detail="properties list is empty")

    config = _config_from_schema(request.config)
    result = run_simulation(properties, config)
    report = generate_report(result, properties, config=config)
    return _report_to_response(report)


@router.post("/analyze/stable", response_model=AnalyzeResponse)
def analyze_stable(request: StableAnalyzeRequest) -> AnalyzeResponse:
    """
    Run multiple simulations and return gap analysis with stability results.

    Each run uses a different random seed. The stability field shows how
    consistently each property receives the same gap signal across runs.
    """
    try:
        properties = load_properties_from_dict(request.properties)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not properties:
        raise HTTPException(status_code=422, detail="properties list is empty")

    num_runs = max(1, min(request.num_runs, 50))  # cap at 50 for safety
    config = _config_from_schema(request.config)

    result = run_simulation(properties, config)
    stability = run_stability_analysis(properties, config, num_runs=num_runs)
    report = generate_report(result, properties, stability=stability, config=config)
    return _report_to_response(report)


@router.post("/analyze/scenario", response_model=AnalyzeResponse)
def analyze_scenario(request: ScenarioRequest) -> AnalyzeResponse:
    """
    Run a predefined scenario and return assessment gap analysis.

    The scenario applies config overrides and a shock schedule on top of the
    supplied base config, then runs a single simulation.
    """
    try:
        properties = load_properties_from_dict(request.properties)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not properties:
        raise HTTPException(status_code=422, detail="properties list is empty")

    if request.scenario not in SCENARIOS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scenario {request.scenario!r}. "
                   f"Available: {sorted(SCENARIOS.keys())}",
        )

    base_config = _config_from_schema(request.config)
    config = apply_scenario(SCENARIOS[request.scenario], base_config)
    result = run_simulation(properties, config)
    report = generate_report(result, properties, config=config)
    return _report_to_response(report)


@router.post("/analyze/compare", response_model=ComparativeReportSchema)
def analyze_compare(request: CompareRequest) -> ComparativeReportSchema:
    """
    Run multiple scenarios on the same properties and return a comparative report.

    Each scenario is run independently; results are diff'd per property and
    per neighbourhood.
    """
    try:
        properties = load_properties_from_dict(request.properties)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not properties:
        raise HTTPException(status_code=422, detail="properties list is empty")

    if not request.scenarios:
        raise HTTPException(status_code=422, detail="scenarios list is empty")

    unknown = [s for s in request.scenarios if s not in SCENARIOS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scenario(s): {unknown!r}. "
                   f"Available: {sorted(SCENARIOS.keys())}",
        )

    base_config = _config_from_schema(request.config)

    try:
        report = run_comparative_analysis(properties, request.scenarios, base_config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    property_comparisons = [
        PropertyComparisonSchema(
            folio_id=pc.folio_id,
            assessed_value=pc.assessed_value,
            scenarios=pc.scenarios,
            gap_signals=pc.gap_signals,
            pressure_scores=pc.pressure_scores,
            most_sensitive_scenario=pc.most_sensitive_scenario,
            sensitivity_range_pct=pc.sensitivity_range_pct,
        )
        for pc in report.property_comparisons
    ]

    return ComparativeReportSchema(
        scenarios_run=report.scenarios_run,
        property_comparisons=property_comparisons,
        neighbourhood_comparison=report.neighbourhood_comparison,
        disclaimer=report.disclaimer,
    )


@router.post("/simulate", response_model=SimulateResponse)
def simulate(request: SimulateRequest) -> SimulateResponse:
    """
    Run the simulation and return raw output (for debugging and exploration).

    Returns transaction-level detail without gap analysis.
    """
    try:
        properties = load_properties_from_dict(request.properties)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not properties:
        raise HTTPException(status_code=422, detail="properties list is empty")

    config = _config_from_schema(request.config)
    result = run_simulation(properties, config)

    transactions = [
        TransactionSchema(
            folio_id=txn.folio_id,
            outcome=txn.outcome.value,
            final_price=txn.final_price,
            rounds=txn.rounds,
            offer_count=len([o for o in txn.all_offers if o.round_number == 1]),
        )
        for txn in result.transactions
    ]

    return SimulateResponse(
        seed=result.seed,
        total_weeks=result.total_weeks,
        properties_sold=result.properties_sold,
        properties_unsold=result.properties_unsold,
        transactions=transactions,
    )
