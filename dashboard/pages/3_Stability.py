"""Page 3 — Multi-seed stability analysis."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sim.engine.simulation import SimulationConfig
from sim.analysis.stability import run_stability_analysis

st.set_page_config(page_title="Stability — Market Sim", page_icon="🏠", layout="wide")

from dashboard.utils import (  # noqa: E402
    DATASET_OPTIONS,
    format_currency,
    load_properties,
    show_disclaimer,
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.markdown("## 🏠 Market Simulation Engine")
st.sidebar.markdown("**BC Assessment Validation Tool**")
st.sidebar.divider()

st.sidebar.header("Stability Parameters")

num_runs = st.sidebar.slider("Number of runs", 3, 25, 10, step=1)
num_agents = st.sidebar.slider("Number of agents", 100, 2000, 500, step=50)
num_weeks = st.sidebar.slider("Number of weeks", 10, 52, 26, step=1)
mortgage_rate = st.sidebar.slider(
    "Mortgage rate (%)", 2.0, 8.0, 5.0, step=0.25, format="%.2f%%"
)
seed = st.sidebar.number_input("Random seed", value=42, step=1)
dataset_name = st.sidebar.selectbox("Dataset", list(DATASET_OPTIONS.keys()))

run_btn = st.sidebar.button("Run Stability Analysis", type="primary", use_container_width=True)

# ── Page title ─────────────────────────────────────────────────────────────────
st.title("Stability Analysis")
st.markdown(
    "Run the simulation multiple times with different seeds to measure how stable "
    "each property's clearing price and gap signal are across runs."
)

if not run_btn:
    st.info(
        "Configure parameters in the sidebar and click **Run Stability Analysis**. "
        "This may take longer than a single run."
    )
    st.stop()

# ── Run ────────────────────────────────────────────────────────────────────────
try:
    properties = load_properties(dataset_name)
    base_config = SimulationConfig(
        num_agents=int(num_agents),
        num_weeks=int(num_weeks),
        contract_rate=mortgage_rate / 100.0,
        seed=int(seed),
    )

    with st.spinner(
        f"Running {num_runs} seeds × {num_agents} agents × {num_weeks} weeks "
        f"({len(properties)} properties)…"
    ):
        stability_results = run_stability_analysis(
            properties=properties,
            base_config=base_config,
            num_runs=int(num_runs),
        )

except Exception as exc:
    st.error(f"Stability analysis failed: {exc}")
    st.stop()

results_list = list(stability_results.values())

# ── Overview: pie chart ────────────────────────────────────────────────────────
st.subheader("Stability Overview")

stability_counts = {"stable": 0, "moderate": 0, "unstable": 0}
for sr in results_list:
    stability_counts[sr.stability] = stability_counts.get(sr.stability, 0) + 1

pie_fig = go.Figure(
    go.Pie(
        labels=[k.title() for k in stability_counts.keys()],
        values=list(stability_counts.values()),
        marker_colors=["#22c55e", "#f59e0b", "#ef4444"],
        hole=0.4,
        textinfo="label+percent",
    )
)
pie_fig.update_layout(
    height=320,
    margin=dict(l=0, r=0, t=20, b=0),
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
)

col_pie, col_metrics = st.columns([1, 2])
with col_pie:
    st.plotly_chart(pie_fig, use_container_width=True)

with col_metrics:
    st.markdown("#### Summary")
    total = len(results_list)
    st.metric("Total Properties", total)
    st.metric("Stable (>80% agreement)", stability_counts["stable"])
    st.metric("Moderate (60–80%)", stability_counts["moderate"])
    st.metric("Unstable (<60%)", stability_counts["unstable"])

st.divider()

# ── Box plots ──────────────────────────────────────────────────────────────────
st.subheader("Clearing Price Distribution per Property")
st.caption("Each box shows the spread of clearing prices across all simulation runs.")

stability_color_map = {
    "stable": "#22c55e",
    "moderate": "#f59e0b",
    "unstable": "#ef4444",
}

# Limit to properties that were sold in at least one run (have non-zero prices)
sold_results = [sr for sr in results_list if any(p > 0 for p in sr.clearing_prices)]

box_fig = go.Figure()

for stability_label in ["stable", "moderate", "unstable"]:
    group = [sr for sr in sold_results if sr.stability == stability_label]
    if not group:
        continue
    for i, sr in enumerate(group):
        prices = [p for p in sr.clearing_prices if p > 0]
        if not prices:
            continue
        box_fig.add_trace(
            go.Box(
                y=prices,
                name=sr.folio_id,
                marker_color=stability_color_map[stability_label],
                legendgroup=stability_label,
                legendgrouptitle_text=stability_label.title() if i == 0 else None,
                showlegend=(i == 0),
                boxmean=True,
            )
        )

box_fig.update_layout(
    xaxis_title="Property (Folio ID)",
    yaxis_title="Clearing Price (CAD)",
    height=500,
    margin=dict(l=0, r=0, t=20, b=0),
    plot_bgcolor="#f8fafc",
    paper_bgcolor="white",
    showlegend=True,
)
box_fig.update_yaxes(tickprefix="$", tickformat=",.0f", gridcolor="#e2e8f0")
box_fig.update_xaxes(tickangle=45)

st.plotly_chart(box_fig, use_container_width=True)

st.divider()

# ── Signal agreement table ─────────────────────────────────────────────────────
st.subheader("Signal Agreement Table")

agree_rows = []
for sr in sorted(results_list, key=lambda x: x.signal_agreement_pct):
    agree_rows.append(
        {
            "Folio": sr.folio_id,
            "Dominant Signal": sr.dominant_signal.replace("_", " ").title(),
            "Agreement %": f"{sr.signal_agreement_pct:.0f}%",
            "Stability": sr.stability.title(),
            "Mean Price": format_currency(sr.mean_clearing_price) if sr.mean_clearing_price > 0 else "Unsold",
            "Std Dev": format_currency(sr.std_clearing_price) if sr.mean_clearing_price > 0 else "—",
            "P10": format_currency(sr.p10_clearing_price) if sr.mean_clearing_price > 0 else "—",
            "P90": format_currency(sr.p90_clearing_price) if sr.mean_clearing_price > 0 else "—",
        }
    )

agree_df = pd.DataFrame(agree_rows)

def _color_stability(val: str) -> str:
    return {
        "Stable": "color: #22c55e",
        "Moderate": "color: #f59e0b",
        "Unstable": "color: #ef4444",
    }.get(val, "")

styled = agree_df.style.applymap(_color_stability, subset=["Stability"])
st.dataframe(styled, use_container_width=True, hide_index=True)

show_disclaimer()
