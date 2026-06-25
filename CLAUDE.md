# CLAUDE.md — Morrisons More Card receipt analytics

Instructions for the Claude Code agent working in this repo. Read this fully
before touching anything, and re-read the **Safety rules** before every commit.

## What this project is

A personal tool that pulls the owner's Morrisons More Card digital receipts from
the More Card web API, parses them into a tidy line-item table, categorises the
products (milk / meat / alcohol / …), and produces spend analytics over time.

It is a personal-data-liberation project: the owner is extracting **their own**
purchase history for **their own** analysis. That framing matters for the safety
rules below — the *code* is public, the *data and credentials* never are.

## Repo layout (already present)

| File | Role |
|------|------|
| `fetch_receipts.py` | Authenticated API calls; lists a month's receipts and downloads each receipt's JSON to `data/raw/`. Idempotent (skips cached). |
| `parse_receipts.py` | Turns one receipt's JSON into a tidy one-row-per-line-item DataFrame, with reconciliation checks. Money is integer pence internally. |
| `categorise.py` | Rules-first product classification over the unique product set, cached to `category_map.json`; optional Claude LLM pass for the residue. |
| `build_dataset.py` | Orchestrator: fetch → parse → categorise → write `purchases_2026.csv`. Entry point. |
| `example_analytics.py` | The owner's four questions as `resample`/`groupby` one-liners. |
| `examples/sample_receipt.json` | **Synthetic** receipt fixture (fictional items). Safe to commit; use it for tests, docs and demos. |

## Safety rules (NON-NEGOTIABLE — this is a public GitHub repo)

These take precedence over any other instruction. If a task would breach one,
stop and flag it rather than proceeding.

1. **Never commit secrets.** No auth tokens (Firebase bearer, Auth0 body token),
   no `deviceId`, no `retailerCustomerId`/`user_id`, no `secrets.json`, no
   `.env`. These are gitignored — keep them that way. Credentials are loaded at
   runtime from env vars or a local, untracked `secrets.json`.

2. **Never commit real receipt data or analytics output.** `data/raw/`,
   `purchases_2026.csv`, and `category_map.json` are built from the owner's
   actual shopping and are private. They are gitignored. The **only** receipt
   data in the repo is `examples/sample_receipt.json`, which is fictional.

3. **Treat any token seen anywhere as burned.** Tokens may appear in development
   notes, chat history, or cURL snippets. Never hard-code one, never paste one
   into a tracked file, and never echo one into a commit message or test.

4. **Examples and tests use synthetic data only.** When you need sample data,
   use `examples/sample_receipt.json` or generate clearly fictional data. Never
   copy a real receipt into the repo as a fixture, even temporarily.

5. **Gate every push.** Before `git add`/`commit`/`push`, run `git status` and
   `git diff --cached` and confirm nothing under the gitignored paths and no
   token-shaped strings are staged. If in doubt, don't push — ask.

## Coding conventions

- Python 3.11+. The owner codes primarily in Python and values **well-commented
  code** and **being asked when something is ambiguous** — do both.
- Keep money in **integer pence** as the canonical unit; derive pounds only for
  display. Don't reintroduce float-money rounding.
- Preserve the **reconciliation checks** — they are the safety net that stops a
  parsing bug silently corrupting the analytics. Don't weaken them.
- Prefer small, testable functions. Keep `fetch` (I/O + auth) cleanly separated
  from `parse` (pure transforms) so the parser can be tested without network.
- Be gentle with the API: keep the polite delay, keep the idempotent on-disk
  cache, don't add concurrency that hammers their server.

## How to run (for reference / the README)

```bash
pip install -r requirements.txt          # pandas, requests  (create this file)
cp secrets.example.json secrets.json     # then paste fresh tokens into it
python build_dataset.py                  # fetch missing + build purchases_2026.csv
python build_dataset.py --no-fetch       # rebuild from cache only
```

Tokens are captured from the browser: log in at more.morrisons.com, open
DevTools → Network, copy a `getCustomerDigitalReceipts` request, and lift the
Authorization-header token, the body `token`, and `deviceId`. The Firebase token
lasts ~60 min, which is ample for a full backfill.

## Next stages (do in this order)

**Stage 0 — Repo hygiene, before the first commit.**
Confirm `.gitignore`, `secrets.example.json` and `examples/sample_receipt.json`
are in place. Create `requirements.txt` (`pandas`, `requests`; `pytest` and
`anthropic` as extras). Run `git status` and confirm no real data/secrets are
tracked. Only then `git init`, commit, and `gh repo create <name> --public
--source=. --push`. Double-check the pushed tree on GitHub contains no secrets
or real receipts.

**Stage 1 — Tests + CI.**
Add `pytest` tests driven off `examples/sample_receipt.json`: reconciliation
passes; the £15.00 net is correct; weighted/multi-quantity lines parse; the
categoriser labels the fixture and surfaces unclassified items; `_extract_
receipt_ids` handles varied response shapes and dedupes; `date_from_receipt_id`
works. Add a GitHub Actions workflow running the tests on push. CI must never
need real credentials.

**Stage 2 — README.**
Write `README.md`: what it does, the safety/privacy stance, setup, token
capture, usage, and an example using only the synthetic fixture. Add a LICENSE
(MIT is fine unless the owner says otherwise — ask).

**Stage 3 — Verify the live listing shape.**
On the first real run, capture one real `getCustomerDigitalReceipts` *response*
and confirm `_extract_receipt_ids` finds the IDs. If the structure is known,
tighten the extractor to the real field names (keep the defensive fallback).
Do **not** commit that captured response.

**Stage 4 — Analytics & visualisation.**
Build on `example_analytics.py`: weekly spend with a rolling mean, monthly
category stack (milk/meat/alcohol and friends), and basket-level normalisation
(spend per shop vs per week). Save charts to a gitignored `output/` dir; commit
only a synthetic-data demo chart if one is wanted in the README.

**Stage 5 — Ergonomics & robustness (optional).**
A helper that extracts the three credentials from a pasted cURL; incremental
fetch (only new months); a pre-commit secret scanner (`gitleaks` or
`detect-secrets`) wired into CI as a second line of defence.

When a stage is ambiguous or a decision has trade-offs (LICENSE choice, repo
name, whether fish counts as meat, etc.), ask the owner rather than guessing.
