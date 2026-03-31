# Payments Reconciliation System

Detects 8 types of mismatches between platform transactions and bank settlements.

## Project Structure

```
recon/
├── reconciler.py        # Core engine (load → reconcile → detect → report)
├── test_reconciler.py   # Test suite for all 8 gap types
├── app.py               # Streamlit dashboard (optional)
├── requirements.txt
└── README.md
```

## Setup

```bash
pip install -r requirements.txt
```

## Run — Command Line

```bash
# Default (looks for transactions.csv and settlements.csv in current folder)
python reconciler.py

# Custom paths
python reconciler.py path/to/transactions.csv path/to/settlements.csv
```

Outputs:
- Prints detailed report to console
- Saves `report_detail.csv` and `report_summary.csv`

## Run — Tests

```bash
python test_reconciler.py
```

Validates all 8 gap types + 1 edge case (clean transaction).

## Run — Streamlit Dashboard

```bash
python -m streamlit run app.py
```

Then open http://localhost:8501, upload both CSVs, and explore results interactively.

## Gap Types Detected

| # | Gap Type                  | Logic Used |
|---|---------------------------|------------|
| 1 | Next-month settlement     | txn month=3, settlement month>3 |
| 2 | Rounding difference       | 0 < |diff| ≤ ₹0.02 |
| 3 | Duplicate settlement      | same txn_id + bank_ref appears 2+ times |
| 4 | Orphan refund             | negative settlement with no matching txn |
| 5 | Failed txn but settled    | status=FAILED but settlement exists |
| 6 | Large amount mismatch     | 10–30% difference between amounts |
| 7 | Missing settlement        | SUCCESS txn with zero settlement records |
| 8 | Currency conversion error | USD txn settled at wrong INR rate |

## Assumptions

- `txn_id` is the primary key for joining both datasets
- One valid transaction should map to exactly one settlement
- Correct USD→INR rate is 83.5
- Rounding threshold is ₹0.02
- Large mismatch range is 10%–30% of transaction amount
- Timezone differences are ignored
