"""
build_dataset.py
----------------
End-to-end: download (or reuse cached) receipts, parse them into line items,
attach categories, and write one tidy CSV you can drive all the analytics off.

Run:
    python build_dataset.py            # fetch missing + build
    python build_dataset.py --no-fetch # build from already-cached data/raw only

Output:
    data/raw/<receiptId>.json   cached raw responses (one per receipt)
    category_map.json           your reviewed description -> category mapping
    purchases_2026.csv          tidy line-item table (the thing to analyse)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from parse_receipts import parse_receipt
from categorise import apply_categories, build_mapping, unclassified_uniques
from fetch_receipts import backfill, date_from_receipt_id


def build(do_fetch: bool = True, raw_dir: str = "data/raw") -> pd.DataFrame:
    raw = Path(raw_dir)

    # 1) Fetch (idempotent — skips anything already cached).
    if do_fetch:
        today = dt.date.today()
        months = list(range(1, today.month + 1)) if today.year == 2026 else list(range(1, 13))
        backfill(2026, months, out_dir=raw)

    # 2) Parse every cached receipt, deriving the date from its filename/id.
    frames, problems = [], []
    for path in sorted(raw.glob("*.json")):
        receipt_id = path.stem
        payload = json.loads(path.read_text())
        df, recon = parse_receipt(payload, receipt_id=receipt_id,
                                  date=date_from_receipt_id(receipt_id))
        if not recon.ok:
            problems.append((receipt_id, recon.messages))
        frames.append(df)

    if not frames:
        raise SystemExit(f"No receipts found in {raw}. Run a fetch first.")
    purchases = pd.concat(frames, ignore_index=True)

    # 3) Categorise (rules first; flip use_llm=True to auto-label the residue).
    mapping = build_mapping(purchases["description"], cache_path="category_map.json")
    purchases = apply_categories(purchases, mapping)

    # 4) Save + report.
    purchases.to_csv("purchases_2026.csv", index=False)

    print(f"\n{len(purchases)} line items across {purchases['receipt_id'].nunique()} receipts")
    print(f"total net spend: £{purchases['net'].sum():,.2f}")
    if problems:
        print(f"\n{len(problems)} receipt(s) failed reconciliation — worth a look:")
        for rid, msgs in problems:
            print(f"  {rid}: {msgs}")
    todo = unclassified_uniques(purchases, mapping)
    if todo:
        print(f"\n{len(todo)} unclassified product(s) to label in category_map.json:")
        for d in todo:
            print("  -", d)
    return purchases


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true",
                    help="build from cached data/raw only, don't hit the API")
    args = ap.parse_args()
    build(do_fetch=not args.no_fetch)
