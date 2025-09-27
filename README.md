# CC → Monarch CSV Converter (Rogers format)

Python CLI to convert Rogers Bank credit‑card CSV exports into a single Monarch Money import file. Supports merging multiple inputs, inclusive date filtering (to‑date defaults to today), and amount sign normalization (purchases → negative; payments/credits → positive). Also supports the weekly **portal table → Google Sheets → CSV** export.

Convert one or more Rogers Bank credit‑card CSV exports into a single **Monarch Money** import CSV.

---

## Compatibility
This tool is built and tested for **Rogers Bank (Canada)** CSV exports. It expects Rogers’ column headers (listed below). Other issuers may use different headers—adapt the script if needed.

---

## Features
- Merge multiple Rogers CSVs into one Monarch‑ready file
- Inclusive **date filtering** on the `Date` column  
  `--from-date YYYY-MM-DD` and optional `--to-date YYYY-MM-DD`  
  If only `--from-date` is provided, `to-date` defaults to **today**
- **Amount normalization**  
  Purchases (CSV **positive**) → **negative** in Monarch (**Uncategorized**)  
  Payments/credits/refunds (CSV **negative**) → **positive** in Monarch (**Credit Card Payment**)
- **Two input formats (auto‑detected):**
  - **Format A — Statement CSV** (official export)
  - **Format B — Website Transaction Table CSV** (copy from portal → paste into Google Sheets → **File → Download → CSV**)
- **Account label**  
  - Statement CSV: derived per row as `Card ****<last4>` from `Card Number`  
  - Portal CSV: uses a **one‑time constant** in the code (e.g., `"Rogers Mastercard ****1234"`)
- No duplicate skipping (keeps everything as provided)

---

## Privacy & Affiliation
- **Local‑only tool**: runs on your computer; does **not** handle bank credentials; makes **no** network calls.
- **No affiliation**: not affiliated with Monarch Money or Rogers Bank.
- **License**: MIT (no warranty). Use at your own risk.
- **Community contributions welcome** (issues/PRs for other banks).

---

## Requirements
- Python **3.8+**

---

## Usage
```bash
# Merge multiple files into one output
python rogers_cc_to_monarch.py in1.csv in2.csv out.csv

# Only from a start date to today
python rogers_cc_to_monarch.py in.csv out.csv --from-date 2025-05-01

# Specific date window (inclusive)
python rogers_cc_to_monarch.py in.csv out.csv --from-date 2025-05-01 --to-date 2025-05-31
```
**Windows path tip:** wrap paths in quotes, e.g.
```bash
python rogers_cc_to_monarch.py "C:\\Users\\you\\Downloads\\rogers_may.csv" "C:\\Users\\you\\Downloads\\monarch_import.csv"
```

---

## Input formats supported

### Format A — **Statement CSV** (Rogers official export)
**Required headers**
```
Date, Posted Date, Reference Number, Activity Type, Activity Status, Card Number,
Merchant Category Description, Merchant Name, Merchant City, Merchant State or Province,
Merchant Country Code, Merchant Postal Code, Amount, Rewards, Name on Card
```
**Example row**
```
2025-01-15,2025-01-16,"123456789123456789123",TRANS,APPROVED,************8888,Quick Payment Service-Fast Food Restaurants,Subway 9999,Toronto,ON,CAN,C9D 2O9,$15.81,,Mark King
```

### Format B — **Portal Table CSV** (via Google Sheets)
Workflow: copy the transactions table from the Rogers portal → paste into Google Sheets → **File → Download → CSV**. Extra columns like `View` are ignored.

**Why this format exists**
- The monthly **Statement CSV** is only available after the statement is generated. The **Portal Table** lets you update Monarch **any time during the month** without waiting for the statement.
- It’s ideal for weekly catch‑ups or mid‑cycle imports so budgets and trends stay current.

**Best practice to avoid duplicates**
- On the Rogers site, use just the **Posted** transactions.
- Also try to import **non‑overlapping date ranges** week to week (or use the tool’s `--from-date/--to-date` to slice cleanly).


**Typical headers** (case‑insensitive; may vary slightly):
```
Date, Transaction description, Transaction category, Amount, View
```
- **Category behavior (portal):** uses the file’s **Transaction category** directly for Category, unless the amount is **negative** (then we set **Credit Card Payment**). If the category cell is empty, we use **Uncategorized**.
- **Account behavior (portal):** the CSV does not include a card number; the script uses a one‑time constant in code `PORTAL_ACCOUNT_LABEL` (default `Rogers Mastercard`). You can change it to `Rogers Mastercard ****<last4>` once and forget it. 

---

## Output (Monarch) CSV headers
```
Date, Merchant, Category, Account, Original Statement, Notes, Amount, Tags
```

## Field mapping & rules
- **Date** → source `Date`
- **Merchant** → Statement: `Merchant Name` • Portal: `Transaction description`/`Description`/`Merchant`
- **Category** → Statement: `Uncategorized` for purchases; `Credit Card Payment` for negative amounts.  
  Portal: **use `Transaction category` directly** (fallback `Uncategorized`), but negative amounts are `Credit Card Payment`.
- **Account** → Statement: `Card ****<last4>` from `Card Number` • Portal: constant label in code
- **Original Statement** → Statement: `Merchant Category Description` (fallback `Merchant Name`) • Portal: the description text
- **Notes** → Statement: `City, Province, Country` • Portal: empty
- **Amount** → numeric only; **negative** for purchases, **positive** for payments/credits/refunds
- **Tags** → empty

---

## Sample input & output (Statement format)
**Sample input (Rogers Statement CSV)**
```csv
Date,Posted Date,Reference Number,Activity Type,Activity Status,Card Number,Merchant Category Description,Merchant Name,Merchant City,Merchant State or Province,Merchant Country Code,Merchant Postal Code,Amount,Rewards,Name on Card
2025-01-15,2025-01-16,"123456789123456789123",TRANS,APPROVED,************8888,Quick Payment Service-Fast Food Restaurants,Subway 9999,Toronto,ON,CAN,C9D 2O9,$15.81,,Mark King
2025-01-16,2025-01-17,"45600000000000000000002",PAYMENT,POSTED,************8888,Payment - Thank You,Rogers Bank,Toronto,ON,CAN,M5V 1A1,($120.00),,Mark King
```
**Resulting output (Monarch CSV)**
```csv
Date,Merchant,Category,Account,Original Statement,Notes,Amount,Tags
2025-01-15,Subway 9999,Uncategorized,Card ****8888,Quick Payment Service-Fast Food Restaurants,"Toronto, ON, CAN",-15.81,
2025-01-16,Rogers Bank,Credit Card Payment,Card ****8888,Payment - Thank You,"Toronto, ON, CAN",120.00,
```

---

## Categorization in Monarch
To keep this tool generic, categorization is minimal. For richer auto‑categorization, import the file and create **Rules** in Monarch (e.g., “Description contains ‘Amazon’ → Shopping”, “contains ‘Restaurants’ → Restaurants”, etc.).

---

## For Support Teams (Monarch / community)
If you choose to share this as a **community workaround** (third‑party, no affiliation), here’s a safe summary:

- **What it does**: reformats Rogers Bank CSV exports into Monarch’s import columns. Runs locally; no credentials; MIT‑licensed.
- **When to use**: while the Rogers connector is unavailable or missing transactions, to keep users unblocked via CSV import.
- **How to use**:
  1) User downloads their Rogers CSV from the bank portal (statement or portal table via Google Sheets → CSV).
  2) Run the CLI to merge/filter and generate `monarch_import.csv`.
  3) Import into Monarch (`Transactions → Import CSV`).
  4) Create Rules (optional) and mark card payments as Transfers.

**Support‑safe blurb (copy/paste):**
> Community workaround (third‑party, not affiliated with Monarch). Use at your own risk. This local CLI reformats Rogers CSVs for Monarch import: https://github.com/jgutierrezo/rogers-cc-to-monarch

---

## Adapting for other banks
If your bank’s CSV headers differ, update in the script:
- Detection lists (`STMT_REQUIRED`, `PORTAL_*`)
- Field lookups like `"Merchant Name"`, `"Amount"`, `"Card Number"`, `"Transaction description"`

Pull requests adding mappings for other Canadian banks are welcome.

