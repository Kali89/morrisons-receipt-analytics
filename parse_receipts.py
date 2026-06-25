"""
parse_receipts.py
-----------------
Turn the JSON returned by Morrisons' `getCustomerDigitalReceiptDetails`
endpoint into a tidy, one-row-per-line-item table that's ready for analysis.

Design notes
============
* All money in the source JSON is in INTEGER PENCE (185 == £1.85). We keep
  pence as the canonical unit (no float rounding errors) and expose pounds
  only as convenience columns derived at the end.
* Per-item discounts live in each item's `rewards` list. The net price you
  actually paid for a line = amount - sum(reward values). This is how a
  £2.25 Pukka pie with a "- £0.50" Pukka offer becomes £1.75.
* The receipt-details payload does NOT contain the shop DATE or a receipt ID.
  Those come from the *listing* call that enumerates a month's receipts, so
  the caller passes them in (see `parse_receipt(..., receipt_id=, date=)`).
* We reconcile every receipt against its own stated totals and raise/return a
  warning if anything doesn't add up, so a parsing bug can never silently
  corrupt your analytics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

@dataclass
class Reconciliation:
    """Outcome of cross-checking a parsed receipt against its own totals.

    `ok` is True only when every check passes. `messages` explains any
    discrepancies so you can eyeball them rather than trusting silently.
    """
    ok: bool
    messages: list[str] = field(default_factory=list)


def _reconcile(receipt_details: dict[str, Any], item_rows: list[dict]) -> Reconciliation:
    """Check the parsed line items against the receipt's stated totals.

    Three independent checks, all in pence:
      1. sum(item gross amounts)        == subtotal
      2. sum(item discount values)      == store savings total
      3. subtotal - savingsTotal        == balance paid

    Note on scope: item `rewards` are *store* savings. A receipt can also carry
    More Card savings and coupon/stamp discounts that are NOT attributable to a
    single line. When those are non-zero, the per-line `net_pence` we compute
    slightly overstates what you actually paid for that line (the receipt-level
    discount isn't apportioned). We surface that as a warning rather than guess
    an apportionment — flag it to me if you ever see it fire and we can decide
    how to handle it.
    """
    msgs: list[str] = []

    subtotal = receipt_details.get("subtotal")
    savings_total = receipt_details.get("savingsTotal")
    balance_paid = receipt_details.get("balancePaid")
    savings = receipt_details.get("savings", {}) or {}
    store_savings = (savings.get("storeSavings", {}) or {}).get("total", 0)
    morecard_savings = (savings.get("moreCardSavings", {}) or {}).get("total", 0)
    coupon_savings = savings.get("couponsStampsDiscounts", []) or []

    gross_sum = sum(r["gross_pence"] for r in item_rows)
    discount_sum = sum(r["discount_pence"] for r in item_rows)

    # Check 1: every line's gross sums to the subtotal.
    if subtotal is not None and gross_sum != subtotal:
        msgs.append(f"gross sum {gross_sum} != subtotal {subtotal} (diff {gross_sum - subtotal})")

    # Check 2: item-level discounts sum to store + More Card savings.
    # Real receipts show More Card rewards ARE in each item's rewards list (the parser
    # sums them all regardless of rewardType), so we compare against the combined total.
    combined_savings = store_savings + morecard_savings
    if discount_sum != combined_savings:
        msgs.append(f"item discounts {discount_sum} != storeSavings+moreCardSavings "
                    f"{combined_savings} (diff {discount_sum - combined_savings})")

    # Check 3: the receipt's own arithmetic holds.
    if None not in (subtotal, savings_total, balance_paid):
        if subtotal - savings_total != balance_paid:
            msgs.append(f"subtotal {subtotal} - savings {savings_total} != balancePaid {balance_paid}")

    # Coupon/stamp discounts are receipt-level and NOT in item rewards — flag if present.
    if coupon_savings:
        msgs.append(f"NOTE: receipt has coupon/stamp discounts not attributed to line items")

    return Reconciliation(ok=len(msgs) == 0, messages=msgs)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept either the full API envelope or just the receiptDetails block.

    The endpoint returns {"result": {"receiptDetails": {...}}}; this lets the
    caller pass that whole thing OR the inner dict, whichever is handier.
    """
    if "result" in payload:
        return payload["result"]["receiptDetails"]
    if "receiptDetails" in payload:
        return payload["receiptDetails"]
    return payload  # assume it's already receiptDetails


def parse_receipt(
    payload: dict[str, Any],
    *,
    receipt_id: str | None = None,
    date: Any = None,
    store: str | None = None,
    strict: bool = False,
) -> tuple[pd.DataFrame, Reconciliation]:
    """Parse one receipt into a tidy DataFrame (one row per line item).

    Parameters
    ----------
    payload      : dict parsed from the endpoint's JSON response.
    receipt_id   : your identifier for this receipt (from the listing call).
    date         : the shop date (from the listing call). Anything pandas can
                   coerce to a datetime; stored verbatim so you can normalise
                   it however you like downstream.
    store        : optional store name/branch, if the listing call provides it.
    strict       : if True, raise ValueError on a failed reconciliation;
                   if False (default), return the Reconciliation so you can log
                   and continue a bulk run without it dying on one odd receipt.

    Returns
    -------
    (df, reconciliation)
        df columns:
          receipt_id, date, store, description,
          quantity, unit_price_pence, gross_pence, discount_pence, net_pence,
          unit_price, gross, discount, net   (the last four are pounds, floats)
    """
    rd = _unwrap(payload)
    items = rd.get("items", []) or []

    rows: list[dict] = []
    for it in items:
        # Sum every reward on the line regardless of rewardType (store / moreCard /
        # coupon) — they all reduce what you paid for this item.
        discount_pence = sum(int(rw.get("value", 0)) for rw in (it.get("rewards") or []))
        gross_pence = int(it["amount"])
        rows.append({
            "receipt_id": receipt_id,
            "date": date,
            "store": store,
            "description": it["description"].strip(),
            "quantity": float(it["quantity"]),          # can be a weight, e.g. 0.62 kg
            "unit_price_pence": int(it["price"]),         # per unit or per kg
            "gross_pence": gross_pence,                   # what the line cost before line discounts
            "discount_pence": discount_pence,             # total discount on the line
            "net_pence": gross_pence - discount_pence,    # what you actually paid for the line
        })

    recon = _reconcile(rd, rows)
    if strict and not recon.ok:
        raise ValueError(f"Receipt {receipt_id} failed reconciliation: {recon.messages}")

    df = pd.DataFrame(rows)
    if not df.empty:
        # Convenience pound columns (derived; pence remain canonical).
        for col in ("unit_price", "gross", "discount", "net"):
            df[col] = df[f"{col}_pence"] / 100.0
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    return df, recon


def parse_many(receipts: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[Reconciliation]]:
    """Parse a batch of receipts into one combined tidy DataFrame.

    `receipts` is a list of dicts shaped like:
        {"payload": <api json>, "receipt_id": "...", "date": "2026-01-14", "store": "..."}
    Only `payload` is required; the rest default to None.
    """
    frames, recons = [], []
    for r in receipts:
        df, recon = parse_receipt(
            r["payload"],
            receipt_id=r.get("receipt_id"),
            date=r.get("date"),
            store=r.get("store"),
            strict=False,
        )
        frames.append(df)
        recons.append(recon)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return combined, recons


# ---------------------------------------------------------------------------
# Self-test: run `python parse_receipts.py path/to/receipt.json`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "full_receipt.json"
    with open(path) as fh:
        payload = json.load(fh)

    df, recon = parse_receipt(payload, receipt_id="demo-001", date="2026-01-14")
    pd.set_option("display.width", 120)
    pd.set_option("display.max_columns", None)
    print(df[["description", "quantity", "gross", "discount", "net"]].to_string(index=False))
    print()
    print(f"lines: {len(df)}   gross: £{df['gross'].sum():.2f}   "
          f"discount: £{df['discount'].sum():.2f}   net: £{df['net'].sum():.2f}")
    print(f"reconciliation ok: {recon.ok}")
    for m in recon.messages:
        print("  -", m)
