"""
Market Simulation CLI — run assessment gap analysis from the command line.

Commands
--------
analyze     Single-run or stability analysis on a property file.
compare     Compare multiple scenarios on the same property file.
smoke       Quick smoke test using built-in sample data.
scenarios   List available predefined scenarios.

Usage examples::

    # Single run
    python scripts/cli.py analyze --data data/properties/sample_victoria.json

    # With output directory
    python scripts/cli.py analyze --data data/properties/sample_victoria.json --output results/

    # Stability analysis
    python scripts/cli.py analyze --data data/properties/sample_victoria.json --stable --runs 10

    # Scenario comparison
    python scripts/cli.py compare \\
        --data data/properties/sample_victoria.json \\
        --scenarios baseline_2024,rate_cut_cycle,recession

    # Quick smoke test
    python scripts/cli.py smoke

    # List scenarios
    python scripts/cli.py scenarios
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.analysis.comparative import run_comparative_analysis
from sim.analysis.report import generate_report
from sim.analysis.stability import run_stability_analysis
from sim.engine.simulation import SimulationConfig, run_simulation
from sim.properties.loader import load_properties_from_dict
from sim.scenarios.presets import SCENARIOS

DISCLAIMER = (
    "This analysis is based on simulated market behavior using rule-based agent "
    "models. Results are indicators for assessment review prioritization, not "
    "appraisal conclusions or market value determinations. All amounts in CAD."
)

# ─── Formatting helpers ────────────────────────────────────────────────────────

def _hr(char: str = "─", width: int = 80) -> str:
    return char * width


def _fmt_money(v: float) -> str:
    return f"${v:,.0f}"


def _signal_marker(signal: str) -> str:
    markers = {
        "under_assessed": "[UNDER]",
        "over_assessed": "[OVER] ",
        "within_tolerance": "[OK]   ",
        "data_insufficient": "[N/A]  ",
    }
    return markers.get(signal, signal)


def _render_text_report(report: Any, scenario_name: str | None = None) -> str:
    lines: list[str] = []
    lines.append(_hr("═"))
    title = "MARKET SIMULATION — ASSESSMENT GAP ANALYSIS"
    if scenario_name:
        title += f" ({scenario_name})"
    lines.append(title)
    lines.append(_hr("═"))
    lines.append(f"Date: {report.run_date}")
    lines.append(f"Properties: {report.total_properties}  "
                 f"Sold: {report.total_sold}  Unsold: {report.total_unsold}  "
                 f"Flagged: {report.flagged_for_review}")

    # Config summary
    cfg = report.config_summary
    lines.append(
        f"Config: {cfg['num_agents']} agents × {cfg['num_weeks']} weeks  "
        f"rate={cfg['contract_rate']:.1%}  seed={cfg['seed']}"
    )
    lines.append("")

    # Property-level table
    lines.append(_hr())
    lines.append("PROPERTY RESULTS")
    lines.append(_hr())
    hdr = f"{'Folio':<22} {'Assessed':>12} {'Clearing':>12} {'Gap%':>7} {'Signal':<10} {'Conf':<8} {'DOM':>5} {'Offers':>6}"
    lines.append(hdr)
    lines.append(_hr("-"))

    for g in sorted(report.property_results, key=lambda x: x.gap_pct, reverse=True):
        clearing_str = _fmt_money(g.simulated_clearing_price) if g.simulated_clearing_price else "  unsold"
        lines.append(
            f"{g.folio_id:<22} {_fmt_money(g.assessed_value):>12} "
            f"{clearing_str:>12} {g.gap_pct:>+7.1f}% "
            f"{_signal_marker(g.gap_signal):<10} {g.confidence:<8} "
            f"{g.days_on_market:>5} {g.offer_count:>6}"
        )
    lines.append("")

    # Neighbourhood summary
    lines.append(_hr())
    lines.append("NEIGHBOURHOOD SUMMARY")
    lines.append(_hr())
    nbhd_hdr = f"{'Neighbourhood':<20} {'Count':>6} {'Avg Gap%':>9} {'Under':>6} {'Over':>5} {'Within':>7} {'Signal'}"
    lines.append(nbhd_hdr)
    lines.append(_hr("-"))
    for n in report.neighbourhood_summaries:
        lines.append(
            f"{n.neighbourhood:<20} {n.property_count:>6} "
            f"{n.avg_gap_pct:>+9.1f}% {n.under_assessed_count:>6} "
            f"{n.over_assessed_count:>5} {n.within_tolerance_count:>7}  "
            f"{n.systemic_signal}"
        )
    lines.append("")

    # Flagged for review
    flagged = [g for g in report.property_results if g.review_recommendation == "flag_for_review"]
    if flagged:
        lines.append(_hr())
        lines.append(f"FLAGGED FOR REVIEW ({len(flagged)} properties)")
        lines.append(_hr())
        for g in sorted(flagged, key=lambda x: abs(x.gap_pct), reverse=True):
            lines.append(
                f"  {g.folio_id:<22} gap={g.gap_pct:+.1f}%  "
                f"signal={g.gap_signal}  confidence={g.confidence}"
            )
        lines.append("")

    if report.systemic_signals:
        lines.append(f"Systemic signals in: {', '.join(report.systemic_signals)}")
        lines.append("")

    lines.append(_hr("─", 60))
    lines.append(DISCLAIMER)

    return "\n".join(lines)


def _render_comparative_report(report: Any) -> str:
    lines: list[str] = []
    lines.append(_hr("═"))
    lines.append("MARKET SIMULATION — COMPARATIVE SCENARIO ANALYSIS")
    lines.append(_hr("═"))
    lines.append(f"Scenarios: {', '.join(report.scenarios_run)}")
    lines.append(f"Properties: {len(report.property_comparisons)}")
    lines.append("")

    # Per-property comparison table
    lines.append(_hr())
    lines.append("PROPERTY COMPARISON")
    lines.append(_hr())

    # Header row
    folio_col = 22
    val_col = 12
    scenario_cols = [f"{s[:10]:<11}" for s in report.scenarios_run]
    lines.append(f"{'Folio':<{folio_col}} {'Assessed':>{val_col}}  " + "  ".join(scenario_cols) + "  Range%")
    lines.append(_hr("-"))

    for pc in report.property_comparisons:
        scenario_parts = []
        for name in report.scenarios_run:
            signal = pc.gap_signals.get(name, "?")
            scenario_parts.append(_signal_marker(signal))
        lines.append(
            f"{pc.folio_id:<{folio_col}} {_fmt_money(pc.assessed_value):>{val_col}}  "
            + "  ".join(f"{p:<11}" for p in scenario_parts)
            + f"  {pc.sensitivity_range_pct:+.1f}%"
        )
    lines.append("")

    # Neighbourhood comparison
    lines.append(_hr())
    lines.append("NEIGHBOURHOOD COMPARISON")
    lines.append(_hr())
    nbhd_hdr = f"{'Neighbourhood':<22}" + "".join(f"  {s[:14]:<14}" for s in report.scenarios_run)
    lines.append(nbhd_hdr)
    lines.append(_hr("-"))
    for nbhd, scenario_signals in sorted(report.neighbourhood_comparison.items()):
        row = f"{nbhd:<22}"
        for name in report.scenarios_run:
            sig = scenario_signals.get(name, "no_data")
            row += f"  {sig:<14}"
        lines.append(row)
    lines.append("")

    lines.append(_hr("─", 60))
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _write_outputs(output_dir: str, stem: str, text: str, data: Any) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    text_path = out / f"{stem}.txt"
    json_path = out / f"{stem}.json"
    text_path.write_text(text, encoding="utf-8")
    print(f"  Text report: {text_path}")
    if hasattr(data, "__dict__"):
        try:
            from dataclasses import asdict
            json_path.write_text(json.dumps(asdict(data), indent=2, default=str), encoding="utf-8")
            print(f"  JSON data:   {json_path}")
        except Exception:
            pass


# ─── Subcommand handlers ───────────────────────────────────────────────────────

def cmd_analyze(args: argparse.Namespace) -> int:
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: data file not found: {data_path}", file=sys.stderr)
        return 1

    with open(data_path, encoding="utf-8") as f:
        raw = json.load(f)

    try:
        properties = load_properties_from_dict(raw)
    except Exception as exc:
        print(f"ERROR loading properties: {exc}", file=sys.stderr)
        return 1

    config = SimulationConfig(
        num_agents=args.agents,
        num_weeks=args.weeks,
        contract_rate=args.rate,
        seed=args.seed,
    )

    print(f"Loaded {len(properties)} properties from {data_path.name}")
    print(f"Config: {config.num_agents} agents × {config.num_weeks} weeks  "
          f"rate={config.contract_rate:.1%}  seed={config.seed}")

    t0 = time.perf_counter()
    result = run_simulation(properties, config)
    elapsed = time.perf_counter() - t0
    print(f"Simulation complete in {elapsed:.2f}s  "
          f"(sold={len(result.properties_sold)}, unsold={len(result.properties_unsold)})")

    stability = None
    if args.stable:
        num_runs = args.runs
        print(f"Running stability analysis ({num_runs} seeds)…")
        t1 = time.perf_counter()
        stability = run_stability_analysis(properties, config, num_runs=num_runs)
        print(f"Stability analysis done in {time.perf_counter() - t1:.2f}s")

    report = generate_report(result, properties, stability=stability, config=config)
    text = _render_text_report(report)
    print()
    print(text)

    if args.output:
        stem = f"analysis_{date.today().isoformat()}"
        _write_outputs(args.output, stem, text, report)

    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: data file not found: {data_path}", file=sys.stderr)
        return 1

    with open(data_path, encoding="utf-8") as f:
        raw = json.load(f)

    try:
        properties = load_properties_from_dict(raw)
    except Exception as exc:
        print(f"ERROR loading properties: {exc}", file=sys.stderr)
        return 1

    scenario_names = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    unknown = [n for n in scenario_names if n not in SCENARIOS]
    if unknown:
        print(f"ERROR: Unknown scenario(s): {unknown}", file=sys.stderr)
        print(f"Available: {sorted(SCENARIOS.keys())}", file=sys.stderr)
        return 1

    base_config = SimulationConfig(
        num_agents=args.agents,
        num_weeks=args.weeks,
        contract_rate=args.rate,
        seed=args.seed,
    )

    print(f"Loaded {len(properties)} properties")
    print(f"Running {len(scenario_names)} scenarios: {scenario_names}")

    t0 = time.perf_counter()
    report = run_comparative_analysis(properties, scenario_names, base_config)
    elapsed = time.perf_counter() - t0
    print(f"Comparative analysis complete in {elapsed:.2f}s")
    print()

    text = _render_comparative_report(report)
    print(text)

    if args.output:
        stem = f"compare_{date.today().isoformat()}"
        _write_outputs(args.output, stem, text, report)

    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    """Quick smoke test: load sample data, run small simulation, verify basic outputs."""
    sample_path = Path(__file__).parent.parent / "data" / "properties" / "sample_victoria.json"
    if not sample_path.exists():
        print(f"ERROR: sample data not found: {sample_path}", file=sys.stderr)
        return 1

    with open(sample_path, encoding="utf-8") as f:
        raw = json.load(f)

    properties = load_properties_from_dict(raw)
    config = SimulationConfig(num_agents=100, num_weeks=10, seed=42)

    print(f"Smoke test: {len(properties)} properties, {config.num_agents} agents, "
          f"{config.num_weeks} weeks")

    t0 = time.perf_counter()
    result = run_simulation(properties, config)
    elapsed = time.perf_counter() - t0

    report = generate_report(result, properties, config=config)

    print(f"  Simulation: {elapsed:.2f}s")
    print(f"  Sold: {report.total_sold}/{report.total_properties}")
    print(f"  Flagged: {report.flagged_for_review}")
    print(f"  Neighbourhoods: {len(report.neighbourhood_summaries)}")

    # Basic sanity checks
    assert report.total_properties > 0, "No properties"
    assert len(report.neighbourhood_summaries) > 0, "No neighbourhood summaries"
    assert report.disclaimer, "Missing disclaimer"

    print("Smoke test PASSED")
    return 0


def cmd_scenarios(args: argparse.Namespace) -> int:
    """List all available predefined scenarios."""
    print(f"{'Scenario Key':<22} {'Name':<28} Description")
    print("─" * 80)
    for key, scenario in sorted(SCENARIOS.items()):
        print(f"{key:<22} {scenario.name:<28} {scenario.description}")
    return 0


# ─── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Market Simulation — BC Assessment gap analysis tool",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── analyze ───────────────────────────────────────────────────────────────
    p_analyze = subparsers.add_parser(
        "analyze",
        help="Run assessment gap analysis on a property file",
    )
    p_analyze.add_argument(
        "--data", required=True, metavar="FILE",
        help="Path to JSON property file",
    )
    p_analyze.add_argument(
        "--output", default=None, metavar="DIR",
        help="Directory to write text + JSON report (optional)",
    )
    p_analyze.add_argument("--agents", type=int, default=500, metavar="N")
    p_analyze.add_argument("--weeks", type=int, default=26, metavar="N")
    p_analyze.add_argument("--rate", type=float, default=0.05, metavar="R")
    p_analyze.add_argument("--seed", type=int, default=42, metavar="S")
    p_analyze.add_argument(
        "--stable", action="store_true",
        help="Run multi-seed stability analysis",
    )
    p_analyze.add_argument(
        "--runs", type=int, default=10, metavar="N",
        help="Number of seeds for --stable (default: 10)",
    )

    # ── compare ───────────────────────────────────────────────────────────────
    p_compare = subparsers.add_parser(
        "compare",
        help="Compare multiple scenarios on a property file",
    )
    p_compare.add_argument(
        "--data", required=True, metavar="FILE",
        help="Path to JSON property file",
    )
    p_compare.add_argument(
        "--scenarios", required=True, metavar="S1,S2,...",
        help="Comma-separated scenario keys (e.g. baseline_2024,rate_cut_cycle)",
    )
    p_compare.add_argument(
        "--output", default=None, metavar="DIR",
        help="Directory to write text + JSON report (optional)",
    )
    p_compare.add_argument("--agents", type=int, default=300, metavar="N")
    p_compare.add_argument("--weeks", type=int, default=26, metavar="N")
    p_compare.add_argument("--rate", type=float, default=0.05, metavar="R")
    p_compare.add_argument("--seed", type=int, default=42, metavar="S")

    # ── smoke ─────────────────────────────────────────────────────────────────
    subparsers.add_parser("smoke", help="Quick smoke test with built-in sample data")

    # ── scenarios ─────────────────────────────────────────────────────────────
    subparsers.add_parser("scenarios", help="List available predefined scenarios")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "analyze": cmd_analyze,
        "compare": cmd_compare,
        "smoke": cmd_smoke,
        "scenarios": cmd_scenarios,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
