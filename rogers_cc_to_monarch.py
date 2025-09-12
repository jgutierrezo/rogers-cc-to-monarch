#!/usr/bin/env python3
"""
rogers_cc_to_monarch.py

Convert one or more credit-card CSV exports into a single Monarch Money import CSV.

- Input columns expected (bank CSV): 
  Date, Posted Date, Reference Number, Activity Type, Activity Status, Card Number,
  Merchant Category Description, Merchant Name, Merchant City, Merchant State or Province,
  Merchant Country Code, Merchant Postal Code, Amount, Rewards, Name on Card

- Output columns (Monarch CSV):
  Date, Merchant, Category, Account, Original Statement, Notes, Amount, Tags

Behavior:
- Processes one or more input CSVs and writes one output CSV (last positional argument).
- Optional inclusive date filtering by the "Date" column:
    --from-date YYYY-MM-DD
    --to-date   YYYY-MM-DD
  If only --from-date is provided, --to-date defaults to today.
- Amount normalization:
    * CSV positive (purchase) -> write NEGATIVE to Monarch (Category="Uncategorized")
    * CSV negative (payment/credit/refund) -> write POSITIVE to Monarch (Category="Credit Card Payment")
- Account column is derived per-row as "Card ****<last4>" from the "Card Number" field.

Notes:
- No duplicate skipping (de-dup) is performed.
- CSVs are assumed to be comma-delimited with UTF-8/UTF-8-SIG encoding.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict

REQUIRED_COLS = [
    "Date", "Amount", "Merchant Name", "Card Number",
    "Merchant Category Description", "Merchant City",
    "Merchant State or Province", "Merchant Country Code",
]

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Convert one or more CC CSVs to a single Monarch CSV (optional date filter)."
    )
    # One or more inputs, last positional is the output file
    p.add_argument(
        "paths", nargs="+",
        help="One or more input CSVs followed by the output CSV (last arg)."
    )
    p.add_argument(
        "--from-date", dest="from_date", default=None,
        help="Start date (inclusive), format YYYY-MM-DD. If provided without --to-date, to-date defaults to today."
    )
    p.add_argument(
        "--to-date", dest="to_date", default=None,
        help="End date (inclusive), format YYYY-MM-DD."
    )
    return p.parse_args()

def parse_date_str(s: str) -> Optional[date]:
    """Parse a string into a date using common formats. Return None if empty/unparseable."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def clean_amount(s: str) -> float:
    """Parse CSV amount preserving sign. Handles $, commas, and (parentheses as negatives)."""
    if s is None:
        return 0.0
    s = s.strip()
    neg_paren = s.startswith("(") and s.endswith(")")
    s = s.replace("(", "").replace(")", "")
    s = re.sub(r"[^\d\.\-]", "", s)  # keep digits, minus, dot
    if s in {"", "-", "."}:
        return 0.0
    val = float(s)
    return -abs(val) if neg_paren else val

def last4(masked: str) -> str:
    """Extract last 4 digits from a masked card number like ************7190."""
    m = re.search(r"(\d{4})\s*$", (masked or "").strip())
    return m.group(1) if m else "XXXX"

def read_cc_csv(path: Path) -> List[Dict[str, str]]:
    """Read a bank CSV and validate required columns. Returns list of dict rows or []."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as f_in:
            reader = csv.DictReader(f_in)
            if not reader.fieldnames:
                print(f"⚠️  Skipping {path}: no headers found.")
                return []
            missing = [c for c in REQUIRED_COLS if c not in reader.fieldnames]
            if missing:
                print(f"⚠️  Skipping {path}: missing required column(s): {', '.join(missing)}")
                return []
            return list(reader)
    except FileNotFoundError:
        print(f"⚠️  Skipping {path}: file not found.")
        return []
    except Exception as e:
        print(f"⚠️  Skipping {path}: {e}")
        return []

def main() -> None:
    args = parse_args()

    if len(args.paths) < 2:
        sys.exit(
            "Provide at least one input CSV and one output CSV.\n"
            "Example:\n"
            "  python rogers_cc_to_monarch.py in1.csv in2.csv out.csv --from-date 2025-05-01\n"
        )

    *input_paths, output_path = args.paths
    input_files = [Path(p) for p in input_paths]
    outp = Path(output_path)

    # Parse inclusive date bounds (filter uses the CSV 'Date' column)
    from_d = parse_date_str(args.from_date) if args.from_date else None
    to_d = parse_date_str(args.to_date) if args.to_date else None
    if args.from_date and not from_d:
        sys.exit("Invalid --from-date. Use YYYY-MM-DD (e.g., 2025-05-01).")
    if args.to_date and not to_d:
        sys.exit("Invalid --to-date. Use YYYY-MM-DD (e.g., 2025-05-31).")
    if from_d and not to_d:
        to_d = datetime.now().date()

    total_read = total_written = total_filtered = total_parse_fail = 0
    out_rows: List[Dict[str, str]] = []

    for path in input_files:
        rows_in = read_cc_csv(path)
        if not rows_in:
            continue

        file_read = len(rows_in)
        file_written = file_filtered = file_parse_fail = 0

        for row in rows_in:
            # Date filter on the "Date" column only
            date_str = (row.get("Date") or "").strip()
            row_d = parse_date_str(date_str)

            if (from_d or to_d):
                if not row_d:
                    file_parse_fail += 1
                    file_filtered += 1
                    continue
                if from_d and row_d < from_d:
                    file_filtered += 1
                    continue
                if to_d and row_d > to_d:
                    file_filtered += 1
                    continue

            merchant = (row.get("Merchant Name") or "").strip()
            category_desc = (row.get("Merchant Category Description") or "").strip()
            city = (row.get("Merchant City") or "").strip()
            prov = (row.get("Merchant State or Province") or "").strip()
            country = (row.get("Merchant Country Code") or "").strip()
            notes = ", ".join([p for p in [city, prov, country] if p])

            amt_raw = clean_amount(row.get("Amount", ""))

            # CSV positive -> purchase -> NEGATIVE in Monarch (Uncategorized)
            # CSV negative -> payment/credit/refund -> POSITIVE in Monarch (Credit Card Payment)
            if amt_raw < 0:
                out_amount = abs(amt_raw)
                out_category = "Credit Card Payment"
            else:
                out_amount = -abs(amt_raw)
                out_category = "Uncategorized"

            acct = f"Card ****{last4(row.get('Card Number',''))}"

            out_rows.append({
                "Date": date_str,
                "Merchant": merchant,
                "Category": out_category,
                "Account": acct,
                "Original Statement": category_desc or merchant,
                "Notes": notes,
                "Amount": f"{out_amount:.2f}",
                "Tags": "",
            })
            file_written += 1

        total_read += file_read
        total_written += file_written
        total_filtered += file_filtered
        total_parse_fail += file_parse_fail

        print(f"• {path.name}: read {file_read}, wrote {file_written}, "
              f"filtered {file_filtered} (unparsed dates: {file_parse_fail})")

    if not out_rows:
        print("⚠️  No rows to write. Check inputs and date filters.")
        return

    # Write output CSV (Monarch format)
    fieldnames = ["Date", "Merchant", "Category", "Account",
                  "Original Statement", "Notes", "Amount", "Tags"]
    with outp.open("w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"\n✅ TOTAL: read {total_read}, wrote {total_written} rows → {outp}")
    if from_d or to_d:
        print(f"   Filtered by date: {total_filtered} (unparsed among them: {total_parse_fail})")
        print(f"   Date window: {from_d if from_d else '—'} to {to_d if to_d else '—'}")
    print("   Date field used for filtering: Date")

if __name__ == "__main__":
    main()
