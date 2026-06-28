"""
fetch_receipts.py
-----------------
Pull your Morrisons digital receipts down to local JSON files, ready for
parse_receipts.parse_many().

How the API works (reverse-engineered from the browser calls)
=============================================================
Two POST endpoints on the same Firebase cloud-functions host, both taking
{"data": {...}} payloads and BOTH carrying two credentials:

  * Authorization header : "Bearer <firebase-token>"   (lives ~60 min)
  * body field "token"   : <auth0-token>                (lives ~240 min)

The 60-minute Firebase token is the binding constraint, but a full year is only
a few dozen calls that finish in seconds, so a single capture is plenty.

  getCustomerDigitalReceipts        -> {"data":{"year":2026,"month":5,"token":..,"deviceId":..}}
        lists a month's receipts. month is the literal calendar month (1-12).
  getCustomerDigitalReceiptDetails  -> {"data":{"receiptId":"108-118-153-2026-05-23","token":..,"deviceId":..}}
        returns the line items (what parse_receipts consumes).

The receiptId ends in the shop date (YYYY-MM-DD), so we derive the date from the
id itself rather than depending on the listing response shape.

Credentials & safety
=====================
Tokens are short-lived secrets. They are NOT hard-coded here: supply them via
environment variables or a local `secrets.json` (which you should .gitignore).
To refresh: log in at more.morrisons.com, open DevTools -> Network, copy a fresh
`getCustomerDigitalReceipts` request and lift the header token, body token and
deviceId out of it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://europe-west2-mktg-mymorrisons-prd-fb-c0e64.cloudfunctions.net"
LIST_ENDPOINT = f"{BASE}/getCustomerDigitalReceipts"
DETAILS_ENDPOINT = f"{BASE}/getCustomerDigitalReceiptDetails"

# A receiptId looks like "108-118-153-2026-05-23": some store/till/txn numbers
# followed by the date. We anchor on the trailing YYYY-MM-DD so the leading part
# can be any number of dash-separated groups.
RECEIPT_ID_RE = re.compile(r"\b[\w-]*?\d{4}-\d{2}-\d{2}\b")
DATE_SUFFIX_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})$")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

@dataclass
class Credentials:
    firebase_token: str   # goes in the Authorization header
    auth0_token: str      # goes in the request body as "token"
    device_id: str


def load_all_accounts(
    secrets_path: str | Path = "secrets.json",
) -> dict[str, "Credentials"]:
    """Return {account_name: Credentials} for every account in secrets.json.

    Handles both the legacy single-account format and the new multi-account format:

      Legacy:        {"firebase_token": "...", "auth0_token": "...", "device_id": "..."}
                     → {"default": Credentials(...)}

      Multi-account: {"matt": {"firebase_token": "...", ...}, "wife": {...}}
                     → {"matt": Credentials(...), "wife": Credentials(...)}

    Keys that start with "_" (like "_comment") are silently skipped.
    """
    p = Path(secrets_path)
    if not p.exists():
        raise RuntimeError(
            f"No secrets file found at {p}. "
            "Copy secrets.example.json → secrets.json and fill in your tokens. "
            "See the module docstring for how to capture fresh tokens."
        )
    d = json.loads(p.read_text())

    # Legacy single-account: top-level keys are credential field names.
    if all(k in d for k in ("firebase_token", "auth0_token", "device_id")):
        return {"default": Credentials(d["firebase_token"], d["auth0_token"], d["device_id"])}

    # Multi-account: top-level keys are account names.
    accounts: dict[str, Credentials] = {}
    for name, acct in d.items():
        if name.startswith("_") or not isinstance(acct, dict):
            continue
        try:
            accounts[name] = Credentials(
                acct["firebase_token"], acct["auth0_token"], acct["device_id"]
            )
        except KeyError as e:
            raise RuntimeError(
                f"Account '{name}' in {secrets_path} is missing field {e}. "
                "Each account needs firebase_token, auth0_token, and device_id."
            ) from e

    if not accounts:
        raise RuntimeError(
            f"No valid accounts found in {secrets_path}. "
            "See secrets.example.json for the expected format."
        )
    return accounts


def load_credentials(
    secrets_path: str | Path = "secrets.json",
    account: str | None = None,
) -> Credentials:
    """Load tokens for one account from env vars or secrets.json.

    Env vars (single-account shortcut — useful for CI):
        MORRISONS_FIREBASE_TOKEN, MORRISONS_AUTH0_TOKEN, MORRISONS_DEVICE_ID

    secrets.json — legacy single-account:
        {"firebase_token": "...", "auth0_token": "...", "device_id": "..."}

    secrets.json — multi-account (new default):
        {"matt": {"firebase_token": "...", ...}, "wife": {"firebase_token": "...", ...}}

    When using multi-account format, pass account="matt" to choose which account.
    If there is only one account in the file, it is selected automatically.
    """
    # Env vars take priority (useful for CI / one-off scripting).
    env = (os.getenv("MORRISONS_FIREBASE_TOKEN"),
           os.getenv("MORRISONS_AUTH0_TOKEN"),
           os.getenv("MORRISONS_DEVICE_ID"))
    if all(env):
        return Credentials(*env)  # type: ignore[arg-type]

    all_accts = load_all_accounts(secrets_path)

    if account is not None:
        if account not in all_accts:
            raise RuntimeError(
                f"Account '{account}' not found in {secrets_path}. "
                f"Available accounts: {sorted(all_accts)}"
            )
        return all_accts[account]

    if len(all_accts) == 1:
        return next(iter(all_accts.values()))

    raise RuntimeError(
        f"secrets.json has multiple accounts ({sorted(all_accts)}). "
        "Specify one: load_credentials(account='matt') or use load_all_accounts()."
    )


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    """A session with sensible retries on transient server errors."""
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.0,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["POST"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://more.morrisons.com",
        "referer": "https://more.morrisons.com/",
        "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"),
    })
    return s


class TokenExpired(RuntimeError):
    """Raised when the API rejects the credentials (usually an expired token)."""


def _post(session: requests.Session, url: str, data: dict[str, Any], creds: Credentials) -> dict:
    """POST one {"data": {...}} call, returning the parsed JSON.

    Always injects the auth0 token + deviceId into the body and the firebase
    token into the Authorization header, mirroring the browser exactly.
    """
    body = {"data": {**data, "token": creds.auth0_token,
                     "mock": False, "mockBehaviour": None, "deviceId": creds.device_id}}
    headers = {"authorization": f"Bearer {creds.firebase_token}"}
    resp = session.post(url, json=body, headers=headers, timeout=30)

    if resp.status_code in (401, 403):
        raise TokenExpired(
            f"{url} returned {resp.status_code} — your tokens have probably expired "
            "(the Firebase one only lasts 60 min). Capture fresh ones and retry."
        )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def date_from_receipt_id(receipt_id: str) -> dt.date | None:
    """Pull the shop date out of a receiptId like '108-118-153-2026-05-23'."""
    m = DATE_SUFFIX_RE.search(receipt_id)
    if not m:
        return None
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _extract_receipt_ids(obj: Any) -> list[str]:
    """Recursively walk the listing response and collect receiptId-shaped strings.

    Done defensively so we don't depend on the exact field name / nesting of the
    listing payload: anything that looks like '<...>-YYYY-MM-DD' is collected.
    If a future response nests them under a known key you can tighten this.
    """
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            # Prefer an explicit field if present, else scan values.
            for k, v in node.items():
                if k in ("receiptId", "id") and isinstance(v, str) and DATE_SUFFIX_RE.search(v):
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and RECEIPT_ID_RE.fullmatch(node) and DATE_SUFFIX_RE.search(node):
            found.append(node)

    walk(obj)
    # De-dupe, keep stable order.
    return sorted(set(found))


def list_receipt_ids(year: int, month: int, creds: Credentials,
                     session: requests.Session | None = None) -> list[str]:
    """Return the receiptIds for one calendar month (month is 1-12)."""
    session = session or _session()
    payload = _post(session, LIST_ENDPOINT, {"year": year, "month": month}, creds)
    return _extract_receipt_ids(payload)


def fetch_receipt_details(receipt_id: str, creds: Credentials,
                          session: requests.Session | None = None) -> dict:
    """Return the full details JSON for one receipt."""
    session = session or _session()
    return _post(session, DETAILS_ENDPOINT, {"receiptId": receipt_id}, creds)


def backfill(year: int, months: list[int], out_dir: str | Path = "data/raw",
             creds: Credentials | None = None, polite_delay: float = 0.5) -> list[dict]:
    """Download every receipt for the given months, caching raw JSON to disk.

    Idempotent: a receipt already saved on disk is skipped, so you can re-run
    freely (e.g. after a token refresh) without re-hitting the API or losing
    data. Returns a manifest: [{receipt_id, date, path}, ...].
    """
    creds = creds or load_credentials()
    session = _session()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    for month in months:
        ids = list_receipt_ids(year, month, creds, session)
        print(f"{year}-{month:02d}: {len(ids)} receipt(s)")
        for rid in ids:
            path = out / f"{rid}.json"
            if not path.exists():
                details = fetch_receipt_details(rid, creds, session)
                path.write_text(json.dumps(details, ensure_ascii=False))
                time.sleep(polite_delay)   # be gentle with their server
            manifest.append({
                "receipt_id": rid,
                "date": date_from_receipt_id(rid),
                "path": str(path),
            })
    return manifest


if __name__ == "__main__":
    # Backfill Jan -> current month of 2026 into data/raw/.
    today = dt.date.today()
    months = list(range(1, today.month + 1)) if today.year == 2026 else list(range(1, 13))
    manifest = backfill(2026, months)
    print(f"\nCached {len(manifest)} receipts. Manifest sample:")
    for row in manifest[:5]:
        print(" ", row)
