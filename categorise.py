"""
categorise.py
-------------
Map Morrisons product descriptions (e.g. "M BRIT S/SKIM MILK") to spend
categories like 'milk', 'meat', 'alcohol' so you can answer "how much do I
spend on X over time".

Strategy (deliberate, and the bit worth getting right)
======================================================
The product strings are abbreviated and messy ("S/SKIM" = semi-skimmed,
"FAD FREE" tuna), which defeats naive keyword matching at the edges. But across
a whole year you only have a few hundred *distinct* strings. So:

  1. Reduce to the UNIQUE set of descriptions.
  2. Classify that small set ONCE, with transparent keyword rules first.
  3. Whatever the rules leave as 'unclassified', either hand-label or send to an
     optional LLM pass (cheap on a few hundred strings), then HUMAN-REVIEW it.
  4. Cache the reviewed mapping to disk and reuse it. The pipeline stays
     deterministic and auditable — your "meat spend" never silently shifts
     because a model felt different on a Tuesday.

Decisions you may want to revisit (flagged rather than assumed):
  * 'meat' here is land animals only; fish (tuna, salmon...) goes to 'fish'.
    If you'd rather lump fish in with meat, move those keywords.
  * 'milk' is milk specifically (you asked about milk). Yogurt/cheese/eggs go
    to 'dairy' so they don't inflate your milk figure. Adjust to taste.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Keyword rules
# ---------------------------------------------------------------------------
# Ordered list of (category, [keyword patterns]). FIRST match wins, so put the
# more specific categories before the more general ones. Keywords are matched
# case-insensitively as whole-ish tokens against the description.
#
# These are a starting point seeded from your sample basket — expect to extend
# them as you see your real product set. The `unclassified_uniques()` helper
# below is how you find what's still missing.

RULES: list[tuple[str, list[str]]] = [
    # alcohol first: a "WINE GUMS" style false positive is why we use word
    # boundaries below, but keep an eye on edge cases like "GINGER".
    ("alcohol", [r"\bwine\b", r"\bbeer\b", r"lager", r"\bgin\b", r"vodka",
                 r"whisky", r"whiskey", r"\brum\b", r"cider", r"\bale\b",
                 r"prosecco", r"champagne", r"\bipa\b", r"brandy", r"tequila",
                 r"liqueur", r"shiraz", r"merlot", r"malbec", r"rioja"]),

    ("milk",    [r"\bmilk\b", r"s/skim", r"semi skim", r"skimmed", r"whole milk"]),

    ("fish",    [r"tuna", r"salmon", r"\bcod\b", r"haddock", r"prawn", r"fish",
                 r"mackerel", r"sardine", r"\bsea\s?bass\b", r"scampi"]),

    ("meat",    [r"chicken", r"\bbeef\b", r"\bpork\b", r"\bham\b", r"bacon",
                 r"sausage", r"\bmince\b", r"steak", r"kidney", r"\blamb\b",
                 r"turkey", r"gammon", r"chorizo", r"salami", r"pepperoni",
                 r"meatball", r"\bpie\b"]),   # NB: "PIE" is a heuristic; a fruit
                                              # pie would land here — review.

    ("dairy",   [r"yogurt", r"yoghurt", r"cheese", r"butter", r"\beggs?\b",
                 r"cream", r"quiche"]),

    ("bakery",  [r"bread", r"naan", r"bagel", r"doughnut", r"roll", r"croissant",
                 r"crumpet", r"muffin", r"baguette"]),

    ("produce", [r"banana", r"apple", r"onion", r"potato", r"broccoli",
                 r"mushroom", r"melon", r"cabbage", r"carrot", r"tomato",
                 r"pepper", r"lettuce", r"cucumber", r"berry", r"grape",
                 r"orange", r"lemon", r"lime", r"avocado", r"spinach"]),

    ("pasta_rice", [r"pasta", r"rigatoni", r"manfredine", r"spaghetti",
                    r"penne", r"\brice\b", r"noodle", r"lasagne", r"macaroni"]),

    ("drinks_soft", [r"juice", r"\bcola\b", r"lemonade", r"squash", r"\bwater\b",
                     r"\btea\b", r"coffee", r"smoothie"]),
]

UNCLASSIFIED = "unclassified"


def _match_rules(description: str) -> str:
    """Return the first category whose keyword matches, else 'unclassified'."""
    text = description.lower()
    for category, patterns in RULES:
        for pat in patterns:
            if re.search(pat, text):
                return category
    return UNCLASSIFIED


# ---------------------------------------------------------------------------
# The cached mapping: description -> category
# ---------------------------------------------------------------------------

def build_mapping(
    descriptions: pd.Series | list[str],
    cache_path: str | Path = "category_map.json",
    use_llm: bool = False,
) -> dict[str, str]:
    """Build (or extend) the description->category mapping for a set of items.

    * Loads any existing reviewed mapping from `cache_path`.
    * For descriptions not already in the cache, applies keyword RULES.
    * Optionally sends whatever is still 'unclassified' to an LLM (see
      `llm_classify`) — but you should still eyeball the result.
    * Writes the merged mapping back to `cache_path` and returns it.

    Nothing here overwrites a label you've already curated in the cache: hand
    edits win over rules, and rules win over the LLM. That ordering is what
    keeps the whole thing reproducible.
    """
    cache_path = Path(cache_path)
    mapping: dict[str, str] = {}
    if cache_path.exists():
        mapping = json.loads(cache_path.read_text())

    uniques = sorted(set(descriptions))
    to_do = [d for d in uniques if d not in mapping]

    # 1) rules pass
    for d in to_do:
        mapping[d] = _match_rules(d)

    # 2) optional LLM pass over whatever the rules couldn't place
    if use_llm:
        still_unknown = [d for d, c in mapping.items() if c == UNCLASSIFIED]
        if still_unknown:
            llm_labels = llm_classify(still_unknown, categories=[c for c, _ in RULES])
            for d, c in llm_labels.items():
                if c:                       # only overwrite if the model gave one
                    mapping[d] = c

    cache_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False))
    return mapping


def apply_categories(
    df: pd.DataFrame,
    mapping: dict[str, str],
    column: str = "description",
    out_column: str = "category",
) -> pd.DataFrame:
    """Attach a `category` column to a tidy line-item DataFrame."""
    df = df.copy()
    df[out_column] = df[column].map(mapping).fillna(UNCLASSIFIED)
    return df


def unclassified_uniques(df: pd.DataFrame, mapping: dict[str, str]) -> list[str]:
    """List the distinct descriptions still unclassified — your to-review queue.

    Run this after each batch; label what's here (edit category_map.json by
    hand, or rerun with use_llm=True) until the list is short enough to ignore.
    """
    cats = df["description"].map(mapping).fillna(UNCLASSIFIED)
    return sorted(df.loc[cats == UNCLASSIFIED, "description"].unique())


# ---------------------------------------------------------------------------
# Optional: LLM assist for the residue
# ---------------------------------------------------------------------------

def llm_classify(descriptions: list[str], categories: list[str]) -> dict[str, str]:
    """Classify a (small) list of product strings with Claude, returning a dict.

    This is OPTIONAL and only worth it for the handful the rules can't place.
    Requires `anthropic` installed and ANTHROPIC_API_KEY set. Returns a mapping
    {description: category}. ALWAYS review the output before trusting it.

    The prompt pins the model to your fixed category list plus 'other', and asks
    for JSON only so the result parses cleanly.
    """
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("pip install anthropic to use llm_classify") from e

    allowed = categories + ["other"]
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    prompt = (
        "You are labelling UK supermarket (Morrisons) product descriptions, which "
        "are heavily abbreviated (e.g. 'M BRIT S/SKIM MILK' = semi-skimmed milk; "
        "the leading 'M ' means Morrisons own-brand).\n"
        f"Assign each item to exactly one of these categories: {allowed}.\n"
        "Use 'other' only if none fit. Reply with JSON ONLY: a single object "
        "mapping each input string to its category, no prose, no code fences.\n\n"
        "Items:\n" + "\n".join(f"- {d}" for d in descriptions)
    )

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in msg.content if block.type == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fail safe: don't crash a pipeline because the model added stray prose.
        print("WARN: could not parse LLM response as JSON; returning no labels")
        return {}


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from parse_receipts import parse_receipt

    path = sys.argv[1] if len(sys.argv) > 1 else "full_receipt.json"
    df, _ = parse_receipt(json.loads(Path(path).read_text()),
                          receipt_id="demo-001", date="2026-01-14")

    mapping = build_mapping(df["description"], cache_path="category_map.json", use_llm=False)
    df = apply_categories(df, mapping)

    summary = (df.groupby("category")["net"].sum().sort_values(ascending=False)
                 .rename("net_spend_gbp").reset_index())
    print(summary.to_string(index=False))
    print("\nstill unclassified:", unclassified_uniques(df, mapping) or "none")
