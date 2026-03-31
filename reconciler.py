"""
Payments Reconciliation System
================================
Compares platform transactions vs bank settlements and detects 8 gap types.
"""

import pandas as pd
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
ROUNDING_THRESHOLD   = 0.02          # max ₹ diff to count as rounding
LARGE_MISMATCH_LOW   = 0.10          # 10% underpayment lower bound
LARGE_MISMATCH_HIGH  = 0.30          # 30% underpayment upper bound
CORRECT_USD_INR_RATE = 83.5          # expected conversion rate
WRONG_RATE_TOLERANCE = 0.03          # 3% tolerance for rate deviation


# ─────────────────────────────────────────────
# 1. LOAD DATA
# ─────────────────────────────────────────────
def load_data(txn_path:  r"C:\Users\vishal sarode\Downloads\transactions.csv" , set_path: r"C:\Users\vishal sarode\Downloads\settlements.csv"):
    """
    Load and validate transactions and settlements CSVs.
    Returns cleaned DataFrames.
    """
    txns = pd.read_csv(txn_path)
    sets = pd.read_csv(set_path)

    # Normalize column names
    txns.columns = txns.columns.str.strip().str.lower()
    sets.columns = sets.columns.str.strip().str.lower()

    # Drop any pre-labeled helper columns so detection is logic-only
    for col in ["gap_type", "note"]:
        if col in sets.columns:
            sets.drop(columns=[col], inplace=True)
        if col in txns.columns:
            txns.drop(columns=[col], inplace=True)

    # Type coercions
    txns["amount"]        = pd.to_numeric(txns["amount"], errors="coerce")
    sets["settled_amount"] = pd.to_numeric(sets["settled_amount"], errors="coerce")

    txns["txn_timestamp"]    = pd.to_datetime(txns["txn_timestamp"], errors="coerce")
    sets["settlement_date"]  = pd.to_datetime(sets["settlement_date"], errors="coerce")

    txns["txn_id"] = txns["txn_id"].astype(str).str.strip()
    sets["txn_id"] = sets["txn_id"].astype(str).str.strip()

    return txns, sets


# ─────────────────────────────────────────────
# 2. RECONCILE DATA
# ─────────────────────────────────────────────
def reconcile_data(txns: pd.DataFrame, sets: pd.DataFrame):
    """
    Merge transactions and settlements on txn_id.
    Handles 1-to-many and missing joins gracefully.
    Returns:
        merged   – inner join (matched records)
        only_txn – transactions with no settlement
        only_set – settlements with no matching transaction
    """
    merged   = txns.merge(sets, on="txn_id", how="inner")
    only_txn = txns[~txns["txn_id"].isin(sets["txn_id"])].copy()
    only_set = sets[~sets["txn_id"].isin(txns["txn_id"])].copy()

    # Compute difference for matched records
    merged["difference"] = merged["settled_amount"] - merged["amount"]

    return merged, only_txn, only_set


# ─────────────────────────────────────────────
# 3. DETECT GAPS
# ─────────────────────────────────────────────
def detect_gaps(merged: pd.DataFrame,
                only_txn: pd.DataFrame,
                only_set: pd.DataFrame):
    """
    Detect all 8 gap types using pure logic (no pre-labeled column).
    Returns a list of issue dicts.
    """
    issues = []

    def add(txn_id, issue_type, txn_amt, settled_amt, diff, explanation):
        issues.append({
            "txn_id":             txn_id,
            "issue_type":         issue_type,
            "transaction_amount": round(txn_amt, 2) if pd.notna(txn_amt) else None,
            "settled_amount":     round(settled_amt, 2) if pd.notna(settled_amt) else None,
            "difference":         round(diff, 2) if pd.notna(diff) else None,
            "explanation":        explanation,
        })

    # ── GAP 1: Next-month settlement ──────────────────────────────────────
    # Txn in March but settled in April (or later month)
    merged["txn_timestamp"]   = pd.to_datetime(merged["txn_timestamp"],   errors="coerce")
    merged["settlement_date"] = pd.to_datetime(merged["settlement_date"], errors="coerce")
    nm = merged[
        (merged["txn_timestamp"].dt.month == 3) &
        (merged["settlement_date"].dt.month > 3)
    ]
    for _, r in nm.iterrows():
        add(r.txn_id, "NEXT_MONTH_SETTLEMENT",
            r.amount, r.settled_amount, r.difference,
            f"Txn on {r.txn_timestamp.date()} settled on {r.settlement_date.date()} "
            f"(crosses month boundary)")

    # ── GAP 2: Rounding difference ────────────────────────────────────────
    # Difference is tiny (0 < |diff| <= threshold) and not already next-month
    nm_ids = set(nm["txn_id"])
    rounding = merged[
        (merged["txn_id"].apply(lambda x: x not in nm_ids)) &
        (merged["difference"].abs() > 0) &
        (merged["difference"].abs() <= ROUNDING_THRESHOLD) &
        (merged["settled_amount"] > 0)
    ]
    for _, r in rounding.iterrows():
        add(r.txn_id, "ROUNDING_DIFFERENCE",
            r.amount, r.settled_amount, r.difference,
            f"Amount diff of ₹{abs(r.difference):.2f} — likely floating-point/rounding error")

    # ── GAP 3: Duplicate settlement ───────────────────────────────────────
    # Same txn_id + bank_ref appears more than once in settlements
    if "bank_ref" in merged.columns:
        dup_check = merged.groupby(["txn_id", "bank_ref"]).size().reset_index(name="count")
        dup_ids   = dup_check[dup_check["count"] > 1]["txn_id"].unique()
        dups      = merged[merged["txn_id"].isin(dup_ids)]
        seen_dups = set()
        for txn_id, grp in dups.groupby("txn_id"):
            if txn_id in seen_dups:
                continue
            seen_dups.add(txn_id)
            total_settled = grp["settled_amount"].sum()
            txn_amt       = grp["amount"].iloc[0]
            add(txn_id, "DUPLICATE_SETTLEMENT",
                txn_amt, total_settled, total_settled - txn_amt,
                f"txn_id settled {len(grp)}x with same bank_ref "
                f"(settlement_ids: {list(grp.get('settlement_id', ['?']))})")

    # ── GAP 4: Orphan refund ──────────────────────────────────────────────
    # Negative settlement whose txn_id doesn't exist in transactions
    orphans = only_set[only_set["settled_amount"] < 0]
    for _, r in orphans.iterrows():
        add(r.txn_id, "ORPHAN_REFUND",
            None, r.settled_amount, r.settled_amount,
            f"Refund of ₹{abs(r.settled_amount):.2f} on {r.settlement_date.date()} "
            f"has no matching original transaction")

    # ── GAP 5: Failed txn but bank settled ───────────────────────────────
    failed_settled = merged[
        (merged["status"].str.upper() == "FAILED") &
        (merged["settled_amount"] > 0)
    ]
    for _, r in failed_settled.iterrows():
        add(r.txn_id, "FAILED_TXN_SETTLED",
            r.amount, r.settled_amount, r.difference,
            f"Platform status=FAILED but bank settled ₹{r.settled_amount:.2f} on "
            f"{r.settlement_date.date()}")

    # ── GAP 6: Large amount mismatch ─────────────────────────────────────
    # Difference is 10–30% of transaction amount (and not rounding/failed)
    failed_ids   = set(failed_settled["txn_id"]) if not failed_settled.empty else set()
    rounding_ids = set(rounding["txn_id"]) if not rounding.empty else set()
    large = merged[
        (~merged["txn_id"].isin(failed_ids)) &
        (~merged["txn_id"].isin(rounding_ids)) &
        (merged["settled_amount"] > 0) &
        (merged["amount"] > 0)
    ].copy()
    large["pct_diff"] = (large["amount"] - large["settled_amount"]).abs() / large["amount"]
    large = large[
        (large["pct_diff"] >= LARGE_MISMATCH_LOW) &
        (large["pct_diff"] <= LARGE_MISMATCH_HIGH)
    ]
    for _, r in large.iterrows():
        add(r.txn_id, "LARGE_AMOUNT_MISMATCH",
            r.amount, r.settled_amount, r.difference,
            f"Settlement is {r.pct_diff*100:.1f}% off — expected ₹{r.amount:.2f}, "
            f"got ₹{r.settled_amount:.2f}")

    # ── GAP 7: Missing settlement ─────────────────────────────────────────
    # SUCCESS transaction with no settlement record at all
    missing = only_txn[only_txn["status"].str.upper() == "SUCCESS"]
    for _, r in missing.iterrows():
        add(r.txn_id, "MISSING_SETTLEMENT",
            r.amount, None, -r.amount,
            f"Transaction ₹{r.amount:.2f} on {r.txn_timestamp.date()} has no bank settlement")

    # ── GAP 8: Currency conversion error ──────────────────────────────────
    # USD transactions where settled INR amount implies wrong conversion rate
    usd_txns = merged[merged["currency"].str.upper() == "USD"].copy()
    if not usd_txns.empty:
        usd_txns["implied_rate"] = usd_txns["settled_amount"] / (
            usd_txns["amount"] / CORRECT_USD_INR_RATE
        )
        wrong_rate = usd_txns[
            (usd_txns["implied_rate"] - CORRECT_USD_INR_RATE).abs() /
            CORRECT_USD_INR_RATE > WRONG_RATE_TOLERANCE
        ]
        for _, r in wrong_rate.iterrows():
            correct_inr = round(r.amount, 2)
            add(r.txn_id, "CURRENCY_CONVERSION_ERROR",
                correct_inr, r.settled_amount, r.difference,
                f"USD txn converted at implied rate {r.implied_rate:.2f} "
                f"instead of {CORRECT_USD_INR_RATE} — "
                f"underpaid by ₹{abs(r.difference):.2f}")

    return pd.DataFrame(issues)


# ─────────────────────────────────────────────
# 4. GENERATE REPORT
# ─────────────────────────────────────────────
def generate_report(issues_df: pd.DataFrame,
                    txns: pd.DataFrame,
                    sets: pd.DataFrame):
    """
    Produce detailed mismatch report + summary statistics.
    Returns (detail_df, summary_df, stats_dict).
    """
    if issues_df.empty:
        print("✅ No issues found — books balance perfectly.")
        return issues_df, pd.DataFrame(), {}

    # ── Detailed report ───────────────────────────────────────────────────
    detail = issues_df[[
        "txn_id", "issue_type", "transaction_amount",
        "settled_amount", "difference", "explanation"
    ]].copy()

    # ── Summary by issue type ─────────────────────────────────────────────
    summary = (
        issues_df
        .groupby("issue_type")
        .agg(
            count        = ("txn_id", "count"),
            total_impact = ("difference", lambda x: round(x.sum(), 2)),
            avg_diff     = ("difference", lambda x: round(x.mean(), 2)),
        )
        .reset_index()
        .rename(columns={
            "issue_type":   "Issue Type",
            "count":        "Count",
            "total_impact": "Total Financial Impact (₹)",
            "avg_diff":     "Avg Difference (₹)",
        })
    )

    # ── Overall stats ─────────────────────────────────────────────────────
    total_txn_amt   = txns["amount"].sum()
    total_set_amt   = sets[sets["settled_amount"] > 0]["settled_amount"].sum()
    overall_diff    = round(total_set_amt - total_txn_amt, 2)
    issue_count     = len(issues_df)
    issue_types     = issues_df["issue_type"].nunique()

    stats = {
        "total_transactions":     len(txns),
        "total_settlements":      len(sets),
        "total_issues_found":     issue_count,
        "unique_issue_types":     issue_types,
        "total_txn_amount":       round(total_txn_amt, 2),
        "total_settled_amount":   round(total_set_amt, 2),
        "overall_difference":     overall_diff,
        "clean_transactions":     len(txns) - issues_df["txn_id"].nunique(),
    }

    return detail, summary, stats


# ─────────────────────────────────────────────
# 5. PRETTY PRINT
# ─────────────────────────────────────────────
def print_report(detail, summary, stats):
    SEP = "─" * 70

    print(f"\n{'═'*70}")
    print("  PAYMENTS RECONCILIATION REPORT")
    print(f"{'═'*70}")

    print(f"\n{'OVERVIEW':}")
    print(SEP)
    for k, v in stats.items():
        label = k.replace("_", " ").title()
        val   = f"₹{v:,.2f}" if "amount" in k or "difference" in k else str(v)
        print(f"  {label:<35} {val}")

    print(f"\n\nSUMMARY BY ISSUE TYPE")
    print(SEP)
    print(summary.to_string(index=False))

    print(f"\n\nDETAILED MISMATCH REPORT")
    print(SEP)
    pd.set_option("display.max_colwidth", 80)
    pd.set_option("display.width", 120)
    for _, row in detail.iterrows():
        print(f"\n  txn_id      : {row.txn_id}")
        print(f"  issue       : {row.issue_type}")
        print(f"  txn amount  : {f'₹{row.transaction_amount:,.2f}' if pd.notna(row.transaction_amount) else 'N/A'}")
        print(f"  settled     : {f'₹{row.settled_amount:,.2f}' if pd.notna(row.settled_amount) else 'N/A'}")
        print(f"  difference  : {f'₹{row.difference:,.2f}' if pd.notna(row.difference) else 'N/A'}")
        print(f"  explanation : {row.explanation}")
    print(f"\n{'═'*70}\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def run(txn_path="transactions.csv", set_path="settlements.csv",
        detail_out="report_detail.csv", summary_out="report_summary.csv"):

    print("Loading data...")
    txns, sets = load_data(txn_path, set_path)

    print("Reconciling...")
    merged, only_txn, only_set = reconcile_data(txns, sets)

    print("Detecting gaps...")
    issues_df = detect_gaps(merged, only_txn, only_set)

    print("Generating report...")
    detail, summary, stats = generate_report(issues_df, txns, sets)

    print_report(detail, summary, stats)

    detail.to_csv(detail_out, index=False)
    summary.to_csv(summary_out, index=False)
    print(f"Reports saved → {detail_out}, {summary_out}")

    return detail, summary, stats


if __name__ == "__main__":
    import sys
    txn = sys.argv[1] if len(sys.argv) > 1 else "transactions.csv"
    stt = sys.argv[2] if len(sys.argv) > 2 else "settlements.csv"
    run(
    r"C:\Users\vishal sarode\Downloads\transactions.csv",
    r"C:\Users\vishal sarode\Downloads\settlements.csv"
    )
