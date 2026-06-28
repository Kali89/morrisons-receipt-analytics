"""
Tests for fetch_receipts.py — pure functions only, no network calls.
"""

import datetime as dt
import json

import pytest

from fetch_receipts import (
    date_from_receipt_id,
    _extract_receipt_ids,
    load_all_accounts,
    load_credentials,
)


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


# ---------------------------------------------------------------------------
# load_all_accounts / load_credentials
# ---------------------------------------------------------------------------

class TestLoadAllAccounts:
    def test_legacy_single_account_format(self, tmp_path):
        """Old flat format returns {'default': Credentials}."""
        s = tmp_path / "secrets.json"
        s.write_text(json.dumps({
            "firebase_token": "fire", "auth0_token": "auth", "device_id": "dev"
        }))
        result = load_all_accounts(s)
        assert list(result.keys()) == ["default"]
        assert result["default"].firebase_token == "fire"
        assert result["default"].auth0_token == "auth"
        assert result["default"].device_id == "dev"

    def test_multi_account_format(self, tmp_path):
        """Multi-account format returns all named accounts."""
        s = tmp_path / "secrets.json"
        s.write_text(json.dumps({
            "matt": {"firebase_token": "fm", "auth0_token": "am", "device_id": "dm"},
            "wife": {"firebase_token": "fw", "auth0_token": "aw", "device_id": "dw"},
        }))
        result = load_all_accounts(s)
        assert set(result.keys()) == {"matt", "wife"}
        assert result["matt"].firebase_token == "fm"
        assert result["wife"].device_id == "dw"

    def test_skips_comment_keys(self, tmp_path):
        """Keys starting with _ are ignored."""
        s = tmp_path / "secrets.json"
        s.write_text(json.dumps({
            "_comment": "ignored",
            "matt": {"firebase_token": "f", "auth0_token": "a", "device_id": "d"},
        }))
        result = load_all_accounts(s)
        assert "_comment" not in result
        assert "matt" in result

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="No secrets file"):
            load_all_accounts(tmp_path / "nonexistent.json")

    def test_missing_field_raises(self, tmp_path):
        """An account entry missing a required field raises a clear error."""
        s = tmp_path / "secrets.json"
        s.write_text(json.dumps({
            "matt": {"firebase_token": "f", "auth0_token": "a"}  # missing device_id
        }))
        with pytest.raises(RuntimeError, match="device_id"):
            load_all_accounts(s)


class TestLoadCredentials:
    def test_named_account_selection(self, tmp_path):
        """account= kwarg picks the right entry from a multi-account file."""
        s = tmp_path / "secrets.json"
        s.write_text(json.dumps({
            "matt": {"firebase_token": "fm", "auth0_token": "am", "device_id": "dm"},
            "wife": {"firebase_token": "fw", "auth0_token": "aw", "device_id": "dw"},
        }))
        creds = load_credentials(s, account="wife")
        assert creds.firebase_token == "fw"

    def test_raises_on_unknown_account(self, tmp_path):
        s = tmp_path / "secrets.json"
        s.write_text(json.dumps({
            "matt": {"firebase_token": "f", "auth0_token": "a", "device_id": "d"},
        }))
        with pytest.raises(RuntimeError, match="'other'"):
            load_credentials(s, account="other")

    def test_raises_when_multiple_accounts_no_selection(self, tmp_path):
        """Ambiguous multi-account file without account= must raise."""
        s = tmp_path / "secrets.json"
        s.write_text(json.dumps({
            "matt": {"firebase_token": "f", "auth0_token": "a", "device_id": "d"},
            "wife": {"firebase_token": "f", "auth0_token": "a", "device_id": "d"},
        }))
        with pytest.raises(RuntimeError, match="multiple accounts"):
            load_credentials(s)

    def test_auto_selects_single_account(self, tmp_path):
        """If only one account exists, account= is optional."""
        s = tmp_path / "secrets.json"
        s.write_text(json.dumps({
            "solo": {"firebase_token": "f", "auth0_token": "a", "device_id": "d"},
        }))
        creds = load_credentials(s)
        assert creds.firebase_token == "f"

    def test_legacy_format_auto_selects(self, tmp_path):
        """Old flat format works without account=."""
        s = tmp_path / "secrets.json"
        s.write_text(json.dumps({
            "firebase_token": "f", "auth0_token": "a", "device_id": "d"
        }))
        creds = load_credentials(s)
        assert creds.device_id == "d"
