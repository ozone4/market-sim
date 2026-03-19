"""Main entry point for the Market Sim Streamlit dashboard."""
import streamlit as st

st.set_page_config(
    page_title="Market Sim",
    page_icon="🏠",
    layout="wide",
)

# Sidebar header shown on every page
st.sidebar.markdown("## 🏠 Market Simulation Engine")
st.sidebar.markdown("**BC Assessment Validation Tool**")
st.sidebar.divider()

st.title("🏠 Market Simulation Engine")
st.markdown(
    "A multi-agent real estate market simulation engine for **BC Assessment validation**. "
    "Demographically realistic buyer agents compete for properties over a configurable "
    "time horizon, producing emergent price signals compared against BC Assessment values."
)

st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    st.markdown("### Pages")
    st.markdown("""
| Page | Description |
|------|-------------|
| **1 Analysis** | Single-run assessment gap analysis with scatter plot and neighbourhood cards |
| **2 Scenarios** | Compare macro-economic scenarios side-by-side |
| **3 Stability** | Multi-seed stability analysis with box plots |
| **4 Demographics** | Visualize the generated buyer agent pool |
| **5 About** | Methodology, architecture, and disclaimer |
""")

with col2:
    st.markdown("### Quick Start")
    st.markdown("""
1. Navigate to **1 Analysis** in the sidebar
2. Adjust simulation parameters
3. Click **Run Simulation**
4. Explore results in the tabs below the chart

For multi-scenario analysis go to **2 Scenarios**.
For statistical robustness go to **3 Stability**.
""")

st.markdown("---")
st.caption(
    "**Disclaimer:** Results are indicators for assessment review prioritization only, "
    "not appraisal conclusions or market value determinations. All amounts in CAD."
)
