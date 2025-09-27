#!/usr/bin/env python3
"""
rogers_cc_to_monarch.py

Convert one or more Rogers Bank CSV files into a single Monarch Money import CSV.
Auto-detects input format:
  - Format A: Monthly "Statement CSV" (official export)
  - Format B: Weekly "Portal Table CSV" (copied to Google Sheets, then Download as CSV)

Output (Monarch):
  Date, Merchant, Category, Account, Original Statement, Notes, Amount, Tags

Behavior:
- Processes one or more input CSVs and writes one output CSV (last positional argument).
- Inclusive date filtering on "Date":
    --from-date YYYY-MM-DD
    --to-date   YYYY-MM-DD
  If only --from-date is provided, --to-date defaults to today.
- Amount normalization:
    * Source positive (purchase)  -> NEGATIVE in Monarch (Category="Uncategorized")
    * Source negative/credit      -> POSITIVE in Monarch (Category="Credit Card Payment")
- Account:
    * Statement CSV: "Card ****<last4>" from Card Number
    * Portal CSV: uses PORTAL_ACCOUNT_LABEL (edit this constant once)

Notes:
- No de-duplication.
- CSVs assumed comma-delimited, UTF-8/UTF-8-SIG.
- Extra columns (e.g., "View") are ignored.
"""

from __future__ import annotations

import argparse, csv, re, sys
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple

# ------------------------
# One-time customization for PORTAL CSVs (no Card Number in that export)
# Edit this once to your preferred label (e.g., "Rogers Mastercard ****8088")
# ------------------------
PORTAL_ACCOUNT_LABEL = "Rogers Mastercard"

# ------------------------
# Detection config
# ------------------------
STMT_REQUIRED = [
    "Date", "Amount", "Merchant Name", "Card Number",
    "Merchant Category Description", "Merchant City",
    "Merchant State or Province", "Merchant Country Code",
]

PORTAL_REQUIRED_MIN = ["Date", "Amount"]
PORTAL_DESC_KEYS = ["Transaction description", "Description", "Merchant", "Merchant Name"]
PORTAL_CAT_KEYS  = ["Transaction category", "Category"]

# ------------------------
# Helpers
# ------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Convert one or more Rogers CSVs to a single Monarch CSV (auto-detect format; optional date filter)."
    )
    p.add_argument("paths", nargs="+", help="One or more input CSVs followed by the output CSV (last arg).")
    p.add_argument("--from-date", dest="from_date", default=None,
                   help="Start date (inclusive), format YYYY-MM-DD. If provided without --to-date, to-date defaults to today.")
    p.add_argument("--to-date", dest="to_date", default=None,
                   help="End date (inclusive), format YYYY-MM-DD.")
    return p.parse_args()

def parse_date_str(s: str) -> Optional[date]:
    if not s: return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def clean_amount(raw: str) -> float:
    if raw is None: return 0.0
    s = str(raw).strip()
    credit_marker = bool(re.search(r"\bCR\b", s, flags=re.IGNORECASE))
    neg_paren = s.startswith("(") and s.endswith(")")
    s_no_paren = s.replace("(", "").replace(")", "")
    explicit_neg = s_no_paren.startswith("-")
    s_num = re.sub(r"[^\d\.\-]", "", s_no_paren)
    if s_num in {"", "-", "."}: return 0.0
    val = float(s_num)
    is_negative = neg_paren or explicit_neg or credit_marker
    return -abs(val) if is_negative else abs(val)

def last4(masked: str) -> str:
    m = re.search(r"(\d{4})\s*$", (masked or "").strip())
    return m.group(1) if m else "XXXX"

def headers_lower_set(headers: List[str]) -> set:
    return { (h or "").strip().lower() for h in headers }

def headers_lower_map(headers: List[str]) -> Dict[str, str]:
    return { (h or "").strip().lower(): h for h in headers }

def get_ci(row: Dict[str, str], *candidates: str) -> str:
    for k in candidates:
        if k in row and row[k] is not None:
            return str(row[k])
    lmap = headers_lower_map(list(row.keys()))
    for k in candidates:
        key = lmap.get(k.lower())
        if key is not None and row.get(key) is not None:
            return str(row[key])
    return ""

def detect_format(headers: List[str]) -> Optional[str]:
    hl = headers_lower_set(headers)
    if {s.lower() for s in STMT_REQUIRED}.issubset(hl):
        return "statement"
    has_min = all(h.lower() in hl for h in PORTAL_REQUIRED_MIN)
    has_desc = any(k.lower() in hl for k in PORTAL_DESC_KEYS)
    if has_min and has_desc:
        return "portal"
    return None

def read_csv_detect(path: Path) -> Tuple[Optional[str], List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as f_in:
            reader = csv.DictReader(f_in)
            if not reader.fieldnames:
                print(f"⚠️  Skipping {path}: no headers found.")
                return None, []
            fmt = detect_format(reader.fieldnames)
            if fmt == "statement":
                hl = headers_lower_set(reader.fieldnames)
                missing = [c for c in STMT_REQUIRED if c.lower() not in hl]
                if missing:
                    print(f"⚠️  {path.name}: looks like Statement, but missing: {', '.join(missing)}")
                    return None, []
                return "statement", list(reader)
            if fmt == "portal":
                return "portal", list(reader)
            print(f"⚠️  Skipping {path}: unrecognized headers.\n    Found: {', '.join(reader.fieldnames)}\n"
                  f"    Expected (Statement example): {', '.join(STMT_REQUIRED)}\n"
                  f"    Expected (Portal example): Date, Transaction description, Transaction category, Amount[, View]")
            return None, []
    except FileNotFoundError:
        print(f"⚠️  Skipping {path}: file not found.")
        return None, []
    except Exception as e:
        print(f"⚠️  Skipping {path}: {e}")
        return None, []

# ------------------------
# Main
# ------------------------
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

    from_d = parse_date_str(args.from_date) if args.from_date else None
    to_d   = parse_date_str(args.to_date)   if args.to_date   else None
    if args.from_date and not from_d:
        sys.exit("Invalid --from-date. Use YYYY-MM-DD (e.g., 2025-05-01).")
    if args.to_date and not to_d:
        sys.exit("Invalid --to-date. Use YYYY-MM-DD (e.g., 2025-05-31).")
    if from_d and not to_d:
        to_d = datetime.now().date()

    total_read = total_written = total_filtered = total_parse_fail = 0
    out_rows: List[Dict[str, str]] = []

    for path in input_files:
        fmt, rows_in = read_csv_detect(path)
        if not rows_in or not fmt:
            continue

        file_read = len(rows_in)
        file_written = file_filtered = file_parse_fail = 0

        for row in rows_in:
            date_str = (get_ci(row, "Date") or "").strip()
            row_d = parse_date_str(date_str)
            if (from_d or to_d):
                if not row_d:
                    file_parse_fail += 1; file_filtered += 1; continue
                if from_d and row_d < from_d:
                    file_filtered += 1; continue
                if to_d and row_d > to_d:
                    file_filtered += 1; continue

            if fmt == "statement":
                merchant = (get_ci(row, "Merchant Name") or "").strip()
                orig_stmt = (get_ci(row, "Merchant Category Description") or "").strip()
                city  = (get_ci(row, "Merchant City") or "").strip()
                prov  = (get_ci(row, "Merchant State or Province") or "").strip()
                country = (get_ci(row, "Merchant Country Code") or "").strip()
                notes = ", ".join([p for p in [city, prov, country] if p])
                acct = f"Card ****{last4(get_ci(row, 'Card Number'))}"
                amt_raw = clean_amount(get_ci(row, "Amount"))
                if amt_raw < 0:
                    out_amount = abs(amt_raw); out_category = "Credit Card Payment"
                else:
                    out_amount = -abs(amt_raw); out_category = "Uncategorized"

            else:  # portal
                merchant = (get_ci(row, *PORTAL_DESC_KEYS) or "").strip()
                portal_cat_raw = (get_ci(row, *PORTAL_CAT_KEYS) or "").strip()
                orig_stmt = merchant  # keep description here
                notes = ""            # portal export lacks location
                acct = PORTAL_ACCOUNT_LABEL or "Rogers Mastercard"
                amt_raw = clean_amount(get_ci(row, "Amount"))
                if amt_raw < 0:
                    out_amount = abs(amt_raw); out_category = "Credit Card Payment"
                else:
                    out_amount = -abs(amt_raw); out_category = (portal_cat_raw or "Uncategorized")

            out_rows.append({
                "Date": date_str,
                "Merchant": merchant,
                "Category": out_category,
                "Account": acct,
                "Original Statement": orig_stmt or merchant,
                "Notes": notes,
                "Amount": f"{out_amount:.2f}",
                "Tags": "",
            })
            file_written += 1

        total_read += file_read
        total_written += file_written
        total_filtered += file_filtered
        total_parse_fail += file_parse_fail

        print(f"• {path.name}: [{fmt}] read {file_read}, wrote {file_written}, "
              f"filtered {file_filtered} (unparsed dates: {file_parse_fail})")

    if not out_rows:
        print("⚠️  No rows to write. Check inputs and date filters.")
        return

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
    print(f"   Portal Account label: {PORTAL_ACCOUNT_LABEL or 'Rogers Mastercard'}")

if __name__ == "__main__":
    main()
