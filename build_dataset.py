"""
build_dataset.py
----------------
End-to-end: download (or reuse cached) receipts for all configured More Card
accounts, parse them into line items, attach categories, and write one tidy CSV.

Run:
    python build_dataset.py                   # fetch all accounts + build
    python build_dataset.py --no-fetch        # build from cache only
    python build_dataset.py --account matt    # single account only

Output:
    data/raw/<account>/<receiptId>.json    cached raw responses, one per receipt
    category_map.json                      your reviewed description → category mapping
    purchases_2026.csv                     tidy line-item table with an 'account' column
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from parse_receipts import parse_receipt
from categorise import apply_categories, build_mapping, unclassified_uniques
from fetch_receipts import backfill, date_from_receipt_id, load_all_accounts


def build(
    do_fetch: bool = True,
    raw_dir: str = "data/raw",
    accounts: list[str] | None = None,
) -> pd.DataFrame:
    """Fetch, parse, categorise, and write purchases_2026.csv.

    Parameters
    ----------
    do_fetch : if False, skip the API calls and parse from disk only.
    raw_dir  : parent directory; per-account receipts go in subdirectories.
    accounts : which account names to include (None = all in secrets.json).
    """
    raw = Path(raw_dir)
    today = dt.date.today()
    months = list(range(1, today.month + 1)) if today.year == 2026 else list(range(1, 13))

    # Warn if legacy flat receipts exist (pre-multi-account layout).
    legacy_files = list(raw.glob("*.json"))
    if legacy_files:
        print(
            f"WARNING: {len(legacy_files)} receipt file(s) found directly in {raw}/ "
            "(legacy single-account layout). These won't be parsed — move them to a "
            "per-account subdirectory first, e.g.:\n"
            f"  mkdir -p {raw}/matt && mv {raw}/*.json {raw}/matt/"
        )

    all_accts = load_all_accounts()
    if accounts:
        missing = set(accounts) - set(all_accts)
        if missing:
            raise SystemExit(f"Unknown account(s): {missing}. Known: {sorted(all_accts)}")
        all_accts = {k: v for k, v in all_accts.items() if k in accounts}

    frames, problems = [], []

    for acct_name, creds in all_accts.items():
        acct_raw = raw / acct_name
        acct_raw.mkdir(parents=True, exist_ok=True)

        # 1) Fetch (idempotent — skips anything already cached).
        if do_fetch:
            print(f"\n── Fetching account: {acct_name} ──")
            backfill(2026, months, out_dir=acct_raw, creds=creds)

        # 2) Parse every cached receipt for this account.
        acct_files = sorted(acct_raw.glob("*.json"))
        if not acct_files:
            print(f"No receipts cached for account '{acct_name}' — skipping.")
            continue

        for path in acct_files:
            receipt_id = path.stem
            payload = json.loads(path.read_text())
            df, recon = parse_receipt(payload, receipt_id=receipt_id,
                                      date=date_from_receipt_id(receipt_id))
            df["account"] = acct_name
            if not recon.ok:
                problems.append((acct_name, receipt_id, recon.messages))
            frames.append(df)

    if not frames:
        raise SystemExit(
            f"No receipts found under {raw}/<account>/. "
            "Run a fetch first, or move legacy receipts to a per-account subdirectory."
        )

    purchases = pd.concat(frames, ignore_index=True)

    # 3) Categorise (rules first; flip use_llm=True to auto-label the residue).
    mapping = build_mapping(purchases["description"], cache_path="category_map.json")
    purchases = apply_categories(purchases, mapping)

    # 4) Save + report.
    purchases.to_csv("purchases_2026.csv", index=False)

    print(f"\n{len(purchases)} line items across {purchases['receipt_id'].nunique()} receipts")
    for acct_name, acct_total in purchases.groupby("account")["net"].sum().items():
        print(f"  {acct_name}: £{acct_total:,.2f}")
    print(f"  total:  £{purchases['net'].sum():,.2f}")

    if problems:
        print(f"\n{len(problems)} receipt(s) failed reconciliation — worth a look:")
        for acct_name, rid, msgs in problems:
            print(f"  [{acct_name}] {rid}: {msgs}")

    todo = unclassified_uniques(purchases, mapping)
    if todo:
        print(f"\n{len(todo)} unclassified product(s) to label in category_map.json:")
        for d in todo:
            print("  -", d)

    return purchases


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true",
                    help="build from cached data/raw/<account>/ only, don't hit the API")
    ap.add_argument("--account", action="append", metavar="NAME",
                    help="include only this account (repeat for multiple). "
                         "Default: all accounts in secrets.json")
    args = ap.parse_args()
    build(do_fetch=not args.no_fetch, accounts=args.account)
