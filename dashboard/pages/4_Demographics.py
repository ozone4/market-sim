"""Page 4 — Agent demographics visualization (no simulation needed)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from sim.agents.generator import (
    generate_buyer_pool,
    VICTORIA_INCOME_DISTRIBUTION,
    VICTORIA_HOUSEHOLD_DISTRIBUTION,
)
from sim.agents.models import HouseholdType

st.set_page_config(page_title="Demographics — Market Sim", page_icon="🏠", layout="wide")

from dashboard.utils import (  # noqa: E402
    DATASET_OPTIONS,
    format_currency,
    load_properties,
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.markdown("## 🏠 Market Simulation Engine")
st.sidebar.markdown("**BC Assessment Validation Tool**")
st.sidebar.divider()

st.sidebar.header("Agent Pool Parameters")

num_agents = st.sidebar.slider("Number of agents", 100, 2000, 500, step=50)
seed = st.sidebar.number_input("Random seed", value=42, step=1)
mortgage_rate = st.sidebar.slider(
    "Mortgage rate (%)", 2.0, 8.0, 5.0, step=0.25, format="%.2f%%"
)
dataset_name = st.sidebar.selectbox("Dataset (for inventory overlay)", list(DATASET_OPTIONS.keys()))

# ── Page title ─────────────────────────────────────────────────────────────────
st.title("Agent Demographics")
st.markdown(
    "Visualize the buyer agent pool generated from 2021 StatsCan demographics for Greater Victoria CMA "
    "(adjusted to 2024 dollars). No simulation run required — just the agent generation step."
)

# ── Generate agents ────────────────────────────────────────────────────────────
rng = np.random.default_rng(int(seed))
agents = generate_buyer_pool(
    num_agents=int(num_agents),
    rng=rng,
    contract_rate=mortgage_rate / 100.0,
)

# Extract data
incomes = [a.financial.annual_income for a in agents]
max_prices = [a.preferences.max_price for a in agents if a.preferences.max_price is not None]
household_types = [a.household_type for a in agents]
first_time_buyers = sum(1 for a in agents if a.financial.is_first_time_buyer)

# Load inventory for overlay
properties = load_properties(dataset_name)
assessed_values = [p.assessed_value for p in properties]

# ── Top-level metrics ──────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Agents", len(agents))
m2.metric("First-Time Buyers", f"{first_time_buyers} ({first_time_buyers/len(agents)*100:.0f}%)")
m3.metric("Median Income", format_currency(float(np.median(incomes))))
m4.metric("Median Max Purchase", format_currency(float(np.median(max_prices))) if max_prices else "N/A")

st.divider()

# ── Row 1: Income distribution + Household type breakdown ─────────────────────
col1, col2 = st.columns(2)

with col1:
    st.subheader("Income Distribution")
    income_fig = go.Figure()

    # Target distribution bands as vertical reference lines
    band_labels = ["$30K–$60K", "$60K–$100K", "$100K–$160K", "$160K–$250K", "$250K–$500K"]
    band_bounds = [30_000, 60_000, 100_000, 160_000, 250_000, 500_000]
    band_colors = ["#bfdbfe", "#93c5fd", "#60a5fa", "#3b82f6", "#1d4ed8"]

    for j, (lo, hi, label, color) in enumerate(
        zip(band_bounds[:-1], band_bounds[1:], band_labels, band_colors)
    ):
        band_incomes = [inc for inc in incomes if lo <= inc < hi]
        if band_incomes:
            income_fig.add_trace(
                go.Histogram(
                    x=band_incomes,
                    name=label,
                    nbinsx=20,
                    marker_color=color,
                    opacity=0.85,
                )
            )

    income_fig.update_layout(
        barmode="stack",
        xaxis_title="Annual Household Income (CAD)",
        yaxis_title="Number of Agents",
        height=380,
        margin=dict(l=0, r=0, t=20, b=0),
        plot_bgcolor="#f8fafc",
        paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    income_fig.update_xaxes(tickprefix="$", tickformat=",.0f", gridcolor="#e2e8f0")
    income_fig.update_yaxes(gridcolor="#e2e8f0")
    st.plotly_chart(income_fig, use_container_width=True)

with col2:
    st.subheader("Household Type Breakdown")
    ht_counts: dict[str, int] = {}
    for ht in household_types:
        ht_counts[ht.value] = ht_counts.get(ht.value, 0) + 1

    ht_labels = [k.replace("_", " ").title() for k in ht_counts.keys()]
    ht_values = list(ht_counts.values())
    ht_colors = [
        "#3b82f6", "#22c55e", "#f59e0b", "#ef4444",
        "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
    ]

    pie_fig = go.Figure(
        go.Pie(
            labels=ht_labels,
            values=ht_values,
            marker_colors=ht_colors[: len(ht_labels)],
            hole=0.35,
            textinfo="label+percent",
        )
    )
    pie_fig.update_layout(
        height=380,
        margin=dict(l=0, r=0, t=20, b=0),
        showlegend=False,
    )
    st.plotly_chart(pie_fig, use_container_width=True)

st.divider()

# ── Row 2: Max purchase price + Affordability vs inventory overlay ─────────────
col3, col4 = st.columns(2)

with col3:
    st.subheader("Max Purchase Price Distribution")
    st.caption("Mortgage qualification ceiling per agent.")

    price_fig = go.Figure()
    price_fig.add_trace(
        go.Histogram(
            x=max_prices,
            nbinsx=40,
            name="Max Purchase Price",
            marker_color="#3b82f6",
            opacity=0.85,
        )
    )
    price_fig.update_layout(
        xaxis_title="Max Purchase Price (CAD)",
        yaxis_title="Number of Agents",
        height=380,
        margin=dict(l=0, r=0, t=20, b=0),
        plot_bgcolor="#f8fafc",
        paper_bgcolor="white",
    )
    price_fig.update_xaxes(tickprefix="$", tickformat=",.0f", gridcolor="#e2e8f0")
    price_fig.update_yaxes(gridcolor="#e2e8f0")
    st.plotly_chart(price_fig, use_container_width=True)

with col4:
    st.subheader("Affordability vs. Inventory")
    st.caption(
        "Agent max purchase prices (blue) overlaid with property assessed values (orange). "
        "Gap between curves indicates supply–demand mismatches."
    )

    overlay_fig = go.Figure()
    overlay_fig.add_trace(
        go.Histogram(
            x=max_prices,
            nbinsx=40,
            name="Agent Max Purchase",
            marker_color="#3b82f6",
            opacity=0.6,
        )
    )
    overlay_fig.add_trace(
        go.Histogram(
            x=assessed_values,
            nbinsx=40,
            name="Property Assessed Value",
            marker_color="#f59e0b",
            opacity=0.6,
        )
    )
    overlay_fig.update_layout(
        barmode="overlay",
        xaxis_title="Value (CAD)",
        yaxis_title="Count",
        height=380,
        margin=dict(l=0, r=0, t=20, b=0),
        plot_bgcolor="#f8fafc",
        paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    overlay_fig.update_xaxes(tickprefix="$", tickformat=",.0f", gridcolor="#e2e8f0")
    overlay_fig.update_yaxes(gridcolor="#e2e8f0")
    st.plotly_chart(overlay_fig, use_container_width=True)
