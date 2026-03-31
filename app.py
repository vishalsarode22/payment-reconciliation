"""
Streamlit Reconciliation Dashboard
Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import io

from reconciler import load_data, reconcile_data, detect_gaps, generate_report

st.set_page_config(
    page_title="Payments Reconciliation",
    page_icon="🏦",
    layout="wide"
)

# ── Styles ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.metric-card {
    background: #f8f9fa; border-radius: 10px;
    padding: 1rem 1.2rem; border: 1px solid #e9ecef;
}
.gap-badge {
    display: inline-block; padding: 2px 10px;
    border-radius: 12px; font-size: 12px; font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

GAP_COLORS = {
    "NEXT_MONTH_SETTLEMENT":    "#2196F3",
    "ROUNDING_DIFFERENCE":      "#FF9800",
    "DUPLICATE_SETTLEMENT":     "#F44336",
    "ORPHAN_REFUND":            "#4CAF50",
    "FAILED_TXN_SETTLED":       "#E91E63",
    "LARGE_AMOUNT_MISMATCH":    "#9C27B0",
    "MISSING_SETTLEMENT":       "#607D8B",
    "CURRENCY_CONVERSION_ERROR":"#009688",
}

# ── Header ─────────────────────────────────────────────────────────────────
st.title("🏦 Payments Reconciliation System")
st.caption("Upload your transactions and settlements CSVs to detect mismatches automatically.")
st.divider()

# ── File Upload ────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    txn_file = st.file_uploader("📄 Upload transactions.csv", type=["csv"])
with col2:
    set_file = st.file_uploader("🏛️ Upload settlements.csv", type=["csv"])

if not txn_file or not set_file:
    st.info("Upload both files above to start reconciliation.")
    st.stop()

# ── Load & Process ─────────────────────────────────────────────────────────
with st.spinner("Reconciling..."):
    txns_df = pd.read_csv(txn_file)
    sets_df = pd.read_csv(set_file)

    # Save to temp paths for load_data
    txn_buf = io.StringIO(txns_df.to_csv(index=False))
    set_buf = io.StringIO(sets_df.to_csv(index=False))

    txns, sets = load_data(txn_buf, set_buf)
    merged, only_txn, only_set = reconcile_data(txns, sets)
    issues_df  = detect_gaps(merged, only_txn, only_set)
    detail, summary, stats = generate_report(issues_df, txns, sets)

# ── Overview Metrics ───────────────────────────────────────────────────────
st.subheader("Overview")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Transactions",     stats.get("total_transactions", 0))
m2.metric("Settlements",      stats.get("total_settlements", 0))
m3.metric("Issues Found",     stats.get("total_issues_found", 0))
m4.metric("Clean Txns",       stats.get("clean_transactions", 0))
m5.metric("Overall Diff (₹)", f"₹{stats.get('overall_difference', 0):,.2f}")

st.divider()

if issues_df.empty:
    st.success("✅ Books balance perfectly — no mismatches detected!")
    st.stop()

# ── Gap Type Breakdown ─────────────────────────────────────────────────────
st.subheader("Gap Type Breakdown")
gap_counts = issues_df["issue_type"].value_counts().reset_index()
gap_counts.columns = ["issue_type", "count"]

cols = st.columns(min(len(gap_counts), 4))
for i, row in gap_counts.iterrows():
    col = cols[i % 4]
    color = GAP_COLORS.get(row.issue_type, "#888")
    col.markdown(f"""
    <div class="metric-card">
        <div style="color:{color}; font-size:11px; font-weight:600; margin-bottom:4px;">
            {row.issue_type.replace('_',' ')}
        </div>
        <div style="font-size:28px; font-weight:700;">{row["count"]}</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ── Summary Table ──────────────────────────────────────────────────────────
st.subheader("Financial Impact by Issue Type")
if not summary.empty:
    st.dataframe(
        summary.style.format({
            "Total Financial Impact (₹)": "₹{:,.2f}",
            "Avg Difference (₹)":         "₹{:,.2f}",
        }),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ── Detailed Issues ────────────────────────────────────────────────────────
st.subheader("Detailed Mismatch Report")

# Filter by gap type
selected_types = st.multiselect(
    "Filter by issue type:",
    options=sorted(issues_df["issue_type"].unique()),
    default=sorted(issues_df["issue_type"].unique()),
)

filtered = detail[detail["issue_type"].isin(selected_types)] if not detail.empty else detail

st.dataframe(
    filtered.style.format({
        "transaction_amount": lambda x: f"₹{x:,.2f}" if pd.notna(x) else "N/A",
        "settled_amount":     lambda x: f"₹{x:,.2f}" if pd.notna(x) else "N/A",
        "difference":         lambda x: f"₹{x:,.2f}" if pd.notna(x) else "N/A",
    }),
    use_container_width=True,
    hide_index=True,
    height=400,
)

# ── Download ───────────────────────────────────────────────────────────────
st.divider()
st.subheader("Download Reports")
dl1, dl2 = st.columns(2)

with dl1:
    if not detail.empty:
        st.download_button(
            "⬇️ Download Detailed Report (CSV)",
            data=detail.to_csv(index=False),
            file_name="reconciliation_detail.csv",
            mime="text/csv",
        )

with dl2:
    if not summary.empty:
        st.download_button(
            "⬇️ Download Summary Report (CSV)",
            data=summary.to_csv(index=False),
            file_name="reconciliation_summary.csv",
            mime="text/csv",
        )
