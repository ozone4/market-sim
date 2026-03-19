"""Page 2 — Scenario comparison."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sim.engine.simulation import SimulationConfig
from sim.scenarios.presets import SCENARIOS
from sim.analysis.comparative import run_comparative_analysis

st.set_page_config(page_title="Scenarios — Market Sim", page_icon="🏠", layout="wide")

from dashboard.utils import (  # noqa: E402
    DATASET_OPTIONS,
    SIGNAL_COLORS,
    SIGNAL_LABELS,
    format_currency,
    gap_signal_color,
    load_properties,
    show_disclaimer,
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.markdown("## 🏠 Market Simulation Engine")
st.sidebar.markdown("**BC Assessment Validation Tool**")
st.sidebar.divider()

st.sidebar.header("Scenario Parameters")

scenario_options = {key: s.name for key, s in SCENARIOS.items()}
selected_keys = st.sidebar.multiselect(
    "Scenarios",
    options=list(scenario_options.keys()),
    default=["baseline_2024", "rate_cut_cycle", "hot_market"],
    format_func=lambda k: scenario_options[k],
)

dataset_name = st.sidebar.selectbox("Dataset", list(DATASET_OPTIONS.keys()))
num_agents = st.sidebar.slider("Base agents", 100, 2000, 500, step=50)
seed = st.sidebar.number_input("Random seed", value=42, step=1)

compare_btn = st.sidebar.button("Compare Scenarios", type="primary", use_container_width=True)

# ── Page title ─────────────────────────────────────────────────────────────────
st.title("Scenario Comparison")
st.markdown("Run multiple macro-economic scenarios on the same property set and compare outcomes.")

if not compare_btn:
    st.info("Select scenarios in the sidebar and click **Compare Scenarios**.")
    st.stop()

if len(selected_keys) < 2:
    st.warning("Select at least 2 scenarios to compare.")
    st.stop()

# ── Run comparative analysis ───────────────────────────────────────────────────
try:
    properties = load_properties(dataset_name)
    base_config = SimulationConfig(num_agents=int(num_agents), seed=int(seed))

    with st.spinner(f"Running {len(selected_keys)} scenarios…"):
        comp_report = run_comparative_analysis(
            properties=properties,
            scenario_names=selected_keys,
            base_config=base_config,
        )

except Exception as exc:
    st.error(f"Comparative analysis failed: {exc}")
    st.stop()

# Build folio → neighbourhood lookup
folio_neighbourhood = {p.folio_id: p.location.neighbourhood for p in properties}

# ── Side-by-side bar chart: avg gap% per neighbourhood per scenario ────────────
st.subheader("Average Gap % by Neighbourhood")

# Aggregate: neighbourhood → scenario → list of gap_pct values
from collections import defaultdict

neighbourhood_gaps: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

for pc in comp_report.property_comparisons:
    neighbourhood = folio_neighbourhood.get(pc.folio_id, "Unknown")
    for scenario_key, clearing_price in pc.scenarios.items():
        if clearing_price > 0:
            gap_pct = (clearing_price - pc.assessed_value) / pc.assessed_value * 100.0
        else:
            gap_pct = 0.0
        neighbourhood_gaps[neighbourhood][scenario_key].append(gap_pct)

# Compute averages
neighbourhoods_sorted = sorted(neighbourhood_gaps.keys())
bar_fig = go.Figure()

# Use a distinct colour per scenario
palette = ["#3b82f6", "#f59e0b", "#22c55e", "#ef4444", "#8b5cf6", "#ec4899"]
for i, key in enumerate(selected_keys):
    avgs = [
        (
            sum(neighbourhood_gaps[n][key]) / len(neighbourhood_gaps[n][key])
            if neighbourhood_gaps[n][key]
            else 0.0
        )
        for n in neighbourhoods_sorted
    ]
    bar_fig.add_trace(
        go.Bar(
            name=SCENARIOS[key].name,
            x=neighbourhoods_sorted,
            y=avgs,
            marker_color=palette[i % len(palette)],
        )
    )

bar_fig.update_layout(
    barmode="group",
    xaxis_title="Neighbourhood",
    yaxis_title="Average Gap % (Clearing vs. Assessed)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=420,
    margin=dict(l=0, r=0, t=40, b=0),
    plot_bgcolor="#f8fafc",
    paper_bgcolor="white",
)
bar_fig.update_yaxes(ticksuffix="%", gridcolor="#e2e8f0")
bar_fig.update_xaxes(gridcolor="#e2e8f0")

st.plotly_chart(bar_fig, use_container_width=True)

# ── Sensitivity table ──────────────────────────────────────────────────────────
st.subheader("Properties Ranked by Sensitivity")
st.caption("Most price-sensitive properties at the top (widest clearing price range across scenarios).")

sensitivity_rows = []
for pc in sorted(
    comp_report.property_comparisons, key=lambda x: x.sensitivity_range_pct, reverse=True
):
    row = {
        "Folio": pc.folio_id,
        "Assessed": format_currency(pc.assessed_value),
        "Sensitivity Range": f"{pc.sensitivity_range_pct:.1f}%",
        "Most Sensitive Scenario": SCENARIOS[pc.most_sensitive_scenario].name
        if pc.most_sensitive_scenario in SCENARIOS
        else pc.most_sensitive_scenario,
    }
    for key in selected_keys:
        price = pc.scenarios.get(key, 0.0)
        row[SCENARIOS[key].name] = format_currency(price) if price > 0 else "Unsold"
    sensitivity_rows.append(row)

sens_df = pd.DataFrame(sensitivity_rows)
st.dataframe(sens_df, use_container_width=True, hide_index=True)

# ── Scenario detail expanders ──────────────────────────────────────────────────
st.subheader("Scenario Details")

for key in selected_keys:
    scenario = SCENARIOS[key]
    with st.expander(f"{scenario.name} — {scenario.description}"):
        col_left, col_right = st.columns([1, 2])

        with col_left:
            st.markdown("**Configuration overrides**")
            if scenario.config_overrides:
                for k, v in scenario.config_overrides.items():
                    st.markdown(f"- `{k}`: `{v}`")
            else:
                st.markdown("_None (uses base config)_")

            st.markdown("**Macro shocks**")
            if scenario.shocks:
                for shock in scenario.shocks:
                    st.markdown(f"- Week {shock.week}: `{shock.shock_type.value}` — {shock.params}")
            else:
                st.markdown("_None_")

        with col_right:
            st.markdown("**Property results under this scenario**")
            detail_rows = []
            for pc in comp_report.property_comparisons:
                price = pc.scenarios.get(key, 0.0)
                signal = pc.gap_signals.get(key, "—")
                detail_rows.append(
                    {
                        "Folio": pc.folio_id,
                        "Assessed": format_currency(pc.assessed_value),
                        "Clearing": format_currency(price) if price > 0 else "Unsold",
                        "Gap %": f"{(price - pc.assessed_value) / pc.assessed_value * 100:+.1f}%"
                        if price > 0
                        else "—",
                        "Signal": SIGNAL_LABELS.get(signal, signal),
                    }
                )
            detail_df = pd.DataFrame(detail_rows)
            st.dataframe(detail_df, use_container_width=True, hide_index=True, height=300)

show_disclaimer()
