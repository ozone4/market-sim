"""Page 1 — Single-run assessment gap analysis."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sim.engine.simulation import SimulationConfig

# Must be first Streamlit call on a page
st.set_page_config(page_title="Analysis — Market Sim", page_icon="🏠", layout="wide")

from dashboard.utils import (  # noqa: E402 — after set_page_config
    DATASET_OPTIONS,
    SIGNAL_COLORS,
    SIGNAL_LABELS,
    format_currency,
    gap_signal_color,
    load_properties,
    run_and_analyze,
    show_disclaimer,
)

# ── Sidebar header ─────────────────────────────────────────────────────────────
st.sidebar.markdown("## 🏠 Market Simulation Engine")
st.sidebar.markdown("**BC Assessment Validation Tool**")
st.sidebar.divider()

st.sidebar.header("Simulation Parameters")

num_agents = st.sidebar.slider("Number of agents", 100, 2000, 500, step=50)
num_weeks = st.sidebar.slider("Number of weeks", 10, 52, 26, step=1)
mortgage_rate = st.sidebar.slider(
    "Mortgage rate (%)", 2.0, 8.0, 5.0, step=0.25, format="%.2f%%"
)
seed = st.sidebar.number_input("Random seed", value=42, step=1)
dataset_name = st.sidebar.selectbox("Dataset", list(DATASET_OPTIONS.keys()))

run_btn = st.sidebar.button("Run Simulation", type="primary", use_container_width=True)

# ── Page title ─────────────────────────────────────────────────────────────────
st.title("Assessment Gap Analysis")
st.markdown("Compare simulated market clearing prices against BC Assessment values.")

if not run_btn:
    st.info("Configure simulation parameters in the sidebar and click **Run Simulation**.")
    st.stop()

# ── Run ────────────────────────────────────────────────────────────────────────
try:
    properties = load_properties(dataset_name)
    config = SimulationConfig(
        num_agents=int(num_agents),
        num_weeks=int(num_weeks),
        contract_rate=mortgage_rate / 100.0,
        seed=int(seed),
    )

    with st.spinner(f"Running {num_agents} agents over {num_weeks} weeks…"):
        result, report = run_and_analyze(properties, config)

except Exception as exc:
    st.error(f"Simulation failed: {exc}")
    st.stop()

# ── Summary metrics ────────────────────────────────────────────────────────────
sold_results = [r for r in report.property_results if r.simulated_clearing_price > 0]
avg_gap = (
    sum(r.gap_pct for r in sold_results) / len(sold_results) if sold_results else 0.0
)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Properties", report.total_properties)
m2.metric("Sold", report.total_sold)
m3.metric("Unsold", report.total_unsold)
m4.metric("Flagged for Review", report.flagged_for_review)
m5.metric("Avg Gap %", f"{avg_gap:+.1f}%")

st.divider()

# ── Scatter plot ───────────────────────────────────────────────────────────────
st.subheader("Assessed Value vs. Clearing Price")

all_assessed = [r.assessed_value for r in report.property_results if r.assessed_value > 0]
ref_min = min(all_assessed) * 0.9 if all_assessed else 0
ref_max = max(all_assessed) * 1.1 if all_assessed else 1_500_000

fig = go.Figure()

# 45-degree reference line (assessed == clearing)
fig.add_trace(
    go.Scatter(
        x=[ref_min, ref_max],
        y=[ref_min, ref_max],
        mode="lines",
        name="Assessed = Clearing",
        line=dict(color="#94a3b8", dash="dash", width=1),
        hoverinfo="skip",
    )
)

for signal, color in SIGNAL_COLORS.items():
    subset = [r for r in report.property_results if r.gap_signal == signal]
    if not subset:
        continue

    # Build hover text
    hover_texts = [
        (
            f"<b>{r.folio_id}</b><br>"
            f"Assessed: {format_currency(r.assessed_value)}<br>"
            f"Clearing: {format_currency(r.simulated_clearing_price)}<br>"
            f"Gap: {r.gap_pct:+.1f}%<br>"
            f"Confidence: {r.confidence}<br>"
            f"DOM: {r.days_on_market}<br>"
            f"Offers: {r.offer_count}"
        )
        for r in subset
    ]

    fig.add_trace(
        go.Scatter(
            x=[r.assessed_value for r in subset],
            y=[r.simulated_clearing_price for r in subset],
            mode="markers",
            name=SIGNAL_LABELS[signal],
            marker=dict(color=color, size=8, opacity=0.8, line=dict(width=0.5, color="white")),
            text=hover_texts,
            hovertemplate="%{text}<extra></extra>",
        )
    )

fig.update_layout(
    xaxis_title="BC Assessed Value (CAD)",
    yaxis_title="Simulated Clearing Price (CAD)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=500,
    margin=dict(l=0, r=0, t=40, b=0),
    plot_bgcolor="#f8fafc",
    paper_bgcolor="white",
)
fig.update_xaxes(tickprefix="$", tickformat=",.0f", gridcolor="#e2e8f0")
fig.update_yaxes(tickprefix="$", tickformat=",.0f", gridcolor="#e2e8f0")

st.plotly_chart(fig, use_container_width=True)

# ── Tabs: table + neighbourhood cards ─────────────────────────────────────────
tab_table, tab_hoods = st.tabs(["Property Results", "Neighbourhood Summaries"])

with tab_table:
    rows = []
    for r in report.property_results:
        rows.append(
            {
                "Folio": r.folio_id,
                "Assessed": format_currency(r.assessed_value),
                "Clearing": format_currency(r.simulated_clearing_price) if r.simulated_clearing_price else "—",
                "Gap %": f"{r.gap_pct:+.1f}%" if r.simulated_clearing_price else "—",
                "Signal": SIGNAL_LABELS.get(r.gap_signal, r.gap_signal),
                "Confidence": r.confidence.title(),
                "Market Pressure": f"{r.market_pressure_score:.1f}",
                "DOM": r.days_on_market,
                "Offers": r.offer_count,
                "Review": r.review_recommendation.replace("_", " ").title(),
            }
        )
    df = pd.DataFrame(rows)

    def _color_signal(val: str) -> str:
        mapping = {
            "Within Tolerance": "color: #22c55e",
            "Under-Assessed": "color: #f59e0b",
            "Over-Assessed": "color: #ef4444",
        }
        return mapping.get(val, "")

    styled = df.style.applymap(_color_signal, subset=["Signal"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

with tab_hoods:
    summaries = report.neighbourhood_summaries
    if not summaries:
        st.info("No neighbourhood data available.")
    else:
        # Lay out cards in rows of 3
        cols_per_row = 3
        for i in range(0, len(summaries), cols_per_row):
            row_summaries = summaries[i : i + cols_per_row]
            cols = st.columns(cols_per_row)
            for col, ns in zip(cols, row_summaries):
                signal_color = {
                    "systemic_under": "#f59e0b",
                    "systemic_over": "#ef4444",
                    "mixed": "#8b5cf6",
                    "within_norms": "#22c55e",
                }.get(ns.systemic_signal, "#6b7280")

                with col:
                    st.markdown(
                        f"""
                        <div style="border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin-bottom:12px">
                            <h4 style="margin:0 0 4px 0">{ns.neighbourhood}</h4>
                            <small style="color:#64748b">{ns.municipality}</small>
                            <hr style="margin:8px 0;border-color:#e2e8f0">
                            <p style="margin:2px 0">
                                <b>Avg Gap:</b> {ns.avg_gap_pct:+.1f}%
                            </p>
                            <p style="margin:2px 0">
                                <b>Signal:</b>
                                <span style="color:{signal_color};font-weight:600">
                                    {ns.systemic_signal.replace("_", " ").title()}
                                </span>
                            </p>
                            <p style="margin:2px 0">
                                <b>Properties:</b> {ns.property_count}
                                &nbsp;|&nbsp;
                                <b>Flagged:</b> {ns.flagged_for_review}
                            </p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

show_disclaimer()
