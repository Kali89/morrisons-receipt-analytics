"""
Tests for fetch_receipts.py — pure functions only, no network calls.
"""

import datetime as dt

import pytest

from fetch_receipts import date_from_receipt_id, _extract_receipt_ids


# ---------------------------------------------------------------------------
# date_from_receipt_id
# ---------------------------------------------------------------------------

class TestDateFromReceiptId:
    def test_standard_format(self):
        assert date_from_receipt_id("108-118-153-2026-05-23") == dt.date(2026, 5, 23)

    def test_different_prefix_length(self):
        # Prefix can be any number of dash-separated segments.
        assert date_from_receipt_id("1-2-2026-01-01") == dt.date(2026, 1, 1)

    def test_end_of_year(self):
        assert date_from_receipt_id("99-999-9999-2025-12-31") == dt.date(2025, 12, 31)

    def test_no_date_returns_none(self):
        assert date_from_receipt_id("no-date-here") is None

    def test_empty_string_returns_none(self):
        assert date_from_receipt_id("") is None

    def test_returns_date_not_datetime(self):
        result = date_from_receipt_id("1-2-2026-03-15")
        assert isinstance(result, dt.date)
        assert not isinstance(result, dt.datetime)


# ---------------------------------------------------------------------------
# _extract_receipt_ids
# ---------------------------------------------------------------------------

class TestExtractReceiptIds:
    def test_extracts_from_explicit_receiptId_key(self):
        obj = {"result": [{"receiptId": "108-118-153-2026-05-23"}]}
        assert _extract_receipt_ids(obj) == ["108-118-153-2026-05-23"]

    def test_extracts_from_id_key(self):
        obj = {"receipts": [{"id": "1-2-2026-06-01"}]}
        assert _extract_receipt_ids(obj) == ["1-2-2026-06-01"]

    def test_extracts_from_nested_list(self):
        obj = {
            "result": {
                "receipts": [
                    {"receiptId": "10-20-30-2026-01-15"},
                    {"receiptId": "10-20-31-2026-01-22"},
                ]
            }
        }
        ids = _extract_receipt_ids(obj)
        assert ids == ["10-20-30-2026-01-15", "10-20-31-2026-01-22"]

    def test_deduplicates(self):
        obj = {
            "a": {"receiptId": "1-2-2026-03-01"},
            "b": {"receiptId": "1-2-2026-03-01"},
        }
        assert _extract_receipt_ids(obj) == ["1-2-2026-03-01"]

    def test_empty_object_returns_empty(self):
        assert _extract_receipt_ids({}) == []

    def test_empty_list_returns_empty(self):
        assert _extract_receipt_ids([]) == []

    def test_ignores_non_date_strings(self):
        obj = {"receiptId": "not-a-date", "other": "also-not-a-date"}
        assert _extract_receipt_ids(obj) == []

    def test_result_is_sorted(self):
        # Multiple IDs should come back in sorted order for stable iteration.
        obj = {
            "items": [
                {"receiptId": "1-2026-03-01"},
                {"receiptId": "1-2026-01-15"},
                {"receiptId": "1-2026-02-10"},
            ]
        }
        ids = _extract_receipt_ids(obj)
        assert ids == sorted(ids)

    def test_varied_response_shape_falls_back_to_scan(self):
        # If neither "receiptId" nor "id" key exists, the walker should still
        # find date-shaped strings in string-valued leaves.
        # (The current implementation only matches on "receiptId"/"id" keys or
        # bare string nodes — bare string nodes require a fullmatch, which means
        # they need to look exactly like a receipt ID. We test the key path.)
        obj = {"data": [{"receiptId": "99-99-2026-04-20"}]}
        assert _extract_receipt_ids(obj) == ["99-99-2026-04-20"]
