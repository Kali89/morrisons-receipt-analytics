"""
Tests for parse_receipts.py, driven entirely off examples/sample_receipt.json.

The fixture has 5 lines:
  EXAMPLE SEEDED BREAD       qty=1  price=100  amount=100  no discount
  DEMO WHOLE MILK            qty=2  price=150  amount=300  no discount
  SAMPLE CHICKEN FILLET      qty=1  price=500  amount=500  no discount
  FAKE LOOSE APPLES          qty=0.5 price=200 amount=100  no discount
  PLACEHOLDER BEER 4PK       qty=1  price=600  amount=600  discount=100 (store reward)

subtotal=1600  savingsTotal=100  balancePaid=1500

Expected net total: 1600 - 100 = 1500p == £15.00
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from parse_receipts import parse_receipt, _unwrap

FIXTURE = Path(__file__).parent.parent / "examples" / "sample_receipt.json"


@pytest.fixture(scope="module")
def payload():
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def parsed(payload):
    df, recon = parse_receipt(payload, receipt_id="test-001", date="2026-01-14")
    return df, recon


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def test_reconciliation_passes(parsed):
    _, recon = parsed
    assert recon.ok, f"Reconciliation failed: {recon.messages}"


def test_reconciliation_no_messages(parsed):
    _, recon = parsed
    # No warning messages for this fixture (no More Card / coupon savings).
    assert recon.messages == []


# ---------------------------------------------------------------------------
# Row count and net total
# ---------------------------------------------------------------------------

def test_row_count(parsed):
    df, _ = parsed
    assert len(df) == 5


def test_net_total_pence(parsed):
    df, _ = parsed
    assert df["net_pence"].sum() == 1500


def test_net_total_pounds(parsed):
    df, _ = parsed
    assert round(df["net"].sum(), 2) == 15.00


def test_gross_total_pence(parsed):
    df, _ = parsed
    assert df["gross_pence"].sum() == 1600


def test_discount_total_pence(parsed):
    df, _ = parsed
    assert df["discount_pence"].sum() == 100


# ---------------------------------------------------------------------------
# Weighted / fractional quantity line
# ---------------------------------------------------------------------------

def test_fractional_quantity_parsed(parsed):
    df, _ = parsed
    apples = df[df["description"] == "FAKE LOOSE APPLES"]
    assert len(apples) == 1
    row = apples.iloc[0]
    assert row["quantity"] == pytest.approx(0.5)
    assert row["unit_price_pence"] == 200
    assert row["gross_pence"] == 100


# ---------------------------------------------------------------------------
# Multi-quantity line
# ---------------------------------------------------------------------------

def test_multi_quantity_parsed(parsed):
    df, _ = parsed
    milk = df[df["description"] == "DEMO WHOLE MILK"]
    assert len(milk) == 1
    row = milk.iloc[0]
    assert row["quantity"] == 2.0
    assert row["unit_price_pence"] == 150
    assert row["gross_pence"] == 300


# ---------------------------------------------------------------------------
# Discount / reward line
# ---------------------------------------------------------------------------

def test_discount_line(parsed):
    df, _ = parsed
    beer = df[df["description"] == "PLACEHOLDER BEER 4PK"]
    assert len(beer) == 1
    row = beer.iloc[0]
    assert row["gross_pence"] == 600
    assert row["discount_pence"] == 100
    assert row["net_pence"] == 500


# ---------------------------------------------------------------------------
# Metadata columns
# ---------------------------------------------------------------------------

def test_receipt_id_propagated(parsed):
    df, _ = parsed
    assert (df["receipt_id"] == "test-001").all()


def test_date_parsed(parsed):
    df, _ = parsed
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert df["date"].iloc[0] == pd.Timestamp("2026-01-14")


# ---------------------------------------------------------------------------
# _unwrap handles different envelope shapes
# ---------------------------------------------------------------------------

def test_unwrap_full_envelope(payload):
    inner = _unwrap(payload)
    assert "items" in inner
    assert "balancePaid" in inner


def test_unwrap_receipt_details_dict(payload):
    inner_direct = payload["result"]["receiptDetails"]
    assert _unwrap(inner_direct) is inner_direct


def test_unwrap_passthrough(payload):
    bare = payload["result"]["receiptDetails"]
    # If neither "result" nor "receiptDetails" key, returns the dict as-is.
    assert _unwrap(bare) is bare


# ---------------------------------------------------------------------------
# strict=True raises on bad data
# ---------------------------------------------------------------------------

def test_strict_mode_raises_on_bad_data():
    bad_payload = {
        "result": {
            "receiptDetails": {
                "items": [
                    {"description": "THING", "quantity": 1, "price": 100, "amount": 100, "rewards": []}
                ],
                "subtotal": 999,   # deliberately wrong
                "savingsTotal": 0,
                "balancePaid": 100,
                "savings": {"storeSavings": {"total": 0}, "moreCardSavings": {"total": 0},
                            "couponsStampsDiscounts": []},
            }
        }
    }
    with pytest.raises(ValueError, match="reconciliation"):
        parse_receipt(bad_payload, strict=True)
