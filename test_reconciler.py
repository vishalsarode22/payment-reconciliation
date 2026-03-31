"""
Test suite — validates detection of all 8 gap types.
Each test builds a minimal synthetic dataset and asserts
the reconciler finds exactly the expected issue type.
"""

import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from reconciler import reconcile_data, detect_gaps

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []


def make_txn(txn_id, amount, status="SUCCESS",
             currency="INR", timestamp="2026-03-15 10:00:00"):
    return pd.DataFrame([{
        "txn_id": txn_id, "customer_id": "CUST001",
        "merchant_id": "MERCH01", "amount": amount,
        "currency": currency, "txn_timestamp": pd.Timestamp(timestamp),
        "payment_method": "UPI", "status": status,
    }])


def make_set(txn_id, settled_amount, date="2026-03-17",
             bank_ref="BREF001", settlement_id="SET001"):
    return pd.DataFrame([{
        "settlement_id": settlement_id, "txn_id": txn_id,
        "settled_amount": settled_amount,
        "settlement_date": pd.Timestamp(date),
        "bank_ref": bank_ref, "bank_batch_id": "BATCH-01",
    }])


def run_and_find(txns, sets, expected_type):
    merged, only_txn, only_set = reconcile_data(txns, sets)
    issues = detect_gaps(merged, only_txn, only_set)
    found = issues["issue_type"].tolist() if not issues.empty else []
    ok = expected_type in found
    return ok, found


# ─────────────────────────────────────────────
# TEST 1 — Next-month settlement
# ─────────────────────────────────────────────
def test_next_month_settlement():
    txns = make_txn("T1", 5000, timestamp="2026-03-30 23:00:00")
    sets = make_set("T1", 5000, date="2026-04-02")
    ok, found = run_and_find(txns, sets, "NEXT_MONTH_SETTLEMENT")
    results.append(("GAP 1 — Next-month settlement", ok, found))


# ─────────────────────────────────────────────
# TEST 2 — Rounding difference
# ─────────────────────────────────────────────
def test_rounding_difference():
    txns = make_txn("T2", 1100.33)
    sets = make_set("T2", 1100.34)
    ok, found = run_and_find(txns, sets, "ROUNDING_DIFFERENCE")
    results.append(("GAP 2 — Rounding difference", ok, found))


# ─────────────────────────────────────────────
# TEST 3 — Duplicate settlement
# ─────────────────────────────────────────────
def test_duplicate_settlement():
    txns = make_txn("T3", 2000)
    s1 = make_set("T3", 2000, bank_ref="BREF-DUP", settlement_id="SET001")
    s2 = make_set("T3", 2000, bank_ref="BREF-DUP", settlement_id="SET002")
    sets = pd.concat([s1, s2], ignore_index=True)
    ok, found = run_and_find(txns, sets, "DUPLICATE_SETTLEMENT")
    results.append(("GAP 3 — Duplicate settlement", ok, found))


# ─────────────────────────────────────────────
# TEST 4 — Orphan refund
# ─────────────────────────────────────────────
def test_orphan_refund():
    txns = make_txn("T4", 3000)                        # real txn
    sets_real   = make_set("T4", 3000)                 # real settlement
    sets_orphan = make_set("T999", -500, settlement_id="SET999")  # orphan
    sets = pd.concat([sets_real, sets_orphan], ignore_index=True)
    ok, found = run_and_find(txns, sets, "ORPHAN_REFUND")
    results.append(("GAP 4 — Orphan refund", ok, found))


# ─────────────────────────────────────────────
# TEST 5 — Failed txn but bank settled
# ─────────────────────────────────────────────
def test_failed_txn_settled():
    txns = make_txn("T5", 4500, status="FAILED")
    sets = make_set("T5", 4500)
    ok, found = run_and_find(txns, sets, "FAILED_TXN_SETTLED")
    results.append(("GAP 5 — Failed txn but settled", ok, found))


# ─────────────────────────────────────────────
# TEST 6 — Large amount mismatch
# ─────────────────────────────────────────────
def test_large_amount_mismatch():
    txns = make_txn("T6", 10000)
    sets = make_set("T6", 7500)   # 25% short
    ok, found = run_and_find(txns, sets, "LARGE_AMOUNT_MISMATCH")
    results.append(("GAP 6 — Large amount mismatch", ok, found))


# ─────────────────────────────────────────────
# TEST 7 — Missing settlement
# ─────────────────────────────────────────────
def test_missing_settlement():
    txns = make_txn("T7", 6000, status="SUCCESS")
    sets = pd.DataFrame(columns=[
        "settlement_id","txn_id","settled_amount",
        "settlement_date","bank_ref","bank_batch_id"
    ])
    ok, found = run_and_find(txns, sets, "MISSING_SETTLEMENT")
    results.append(("GAP 7 — Missing settlement", ok, found))


# ─────────────────────────────────────────────
# TEST 8 — Currency conversion error
# ─────────────────────────────────────────────
def test_currency_conversion_error():
    # USD txn: $200 at correct rate 83.5 = ₹16,700
    # Bank settles at wrong rate 80.0   = ₹16,000
    txns = make_txn("T8", 200 * 83.5, currency="USD")   # ₹16,700 in platform
    sets = make_set("T8", 200 * 80.0)                   # ₹16,000 settled
    ok, found = run_and_find(txns, sets, "CURRENCY_CONVERSION_ERROR")
    results.append(("GAP 8 — Currency conversion error", ok, found))


# ─────────────────────────────────────────────
# EDGE CASE — Clean transaction (no issues)
# ─────────────────────────────────────────────
def test_clean_transaction():
    txns = make_txn("T_CLEAN", 5000)
    sets = make_set("T_CLEAN", 5000)
    merged, only_txn, only_set = reconcile_data(txns, sets)
    issues = detect_gaps(merged, only_txn, only_set)
    ok = issues.empty
    results.append(("EDGE — Clean transaction has no issues", ok, []))


# ─────────────────────────────────────────────
# RUN ALL
# ─────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        test_next_month_settlement,
        test_rounding_difference,
        test_duplicate_settlement,
        test_orphan_refund,
        test_failed_txn_settled,
        test_large_amount_mismatch,
        test_missing_settlement,
        test_currency_conversion_error,
        test_clean_transaction,
    ]

    print("\n" + "═" * 60)
    print("  RECONCILIATION TEST SUITE")
    print("═" * 60)

    for t in tests:
        t()

    print()
    passed = 0
    for name, ok, found in results:
        status = PASS if ok else FAIL
        if ok:
            passed += 1
        print(f"  {status}  {name}")
        if not ok:
            print(f"         Expected type not found. Got: {found}")

    print(f"\n  Result: {passed}/{len(results)} tests passed")
    print("═" * 60 + "\n")

    if passed < len(results):
        sys.exit(1)
