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
    # alcohol first — keep word boundaries tight to avoid "WINE GUMS" etc.
    ("alcohol", [r"\bwine\b", r"\bbeer\b", r"lager", r"\bgin\b", r"vodka",
                 r"whisky", r"whiskey", r"\brum\b", r"cider", r"\bale\b",
                 r"prosecco", r"champagne", r"\bipa\b", r"brandy", r"tequila",
                 r"liqueur", r"shiraz", r"merlot", r"malbec", r"rioja",
                 r"stout", r"bitter", r"porter", r"pale\s?ale", r"pilsner",
                 # grape varieties / styles found in real baskets
                 r"primitivo", r"ros[eé]", r"\brouge\b", r"pinot", r"grigio",
                 # UK brewery / brand names
                 r"doom\s?bar", r"ghost\s?ship", r"theakston", r"marston",
                 r"daleside", r"black\s?sheep", r"white\s?rat",
                 r"sharps?\b", r"sharp'?s", r"rocky\s?mountain",
                 # catch generic "4PK", "6PK" beer packs not otherwise matched
                 r"\d+\s?pk\b"]),

    ("milk",    [r"\bmilk\b", r"s/skim", r"semi.?skim", r"skimmed",
                 r"whole milk", r"oat\s?milk", r"soy\s?milk"]),

    # household before fish/dairy so "FAIRY WASHING" → household not dairy
    ("household", [r"washing.up", r"washing liquid", r"washing gel",
                   r"fairy\b", r"non.?bio", r"vanish", r"firelighter",
                   r"bar.?be.?quick",           # BBQ fuel
                   r"cling.?film", r"\bfoil\b", r"garden twine",
                   r"andrex", r"kleenex", r"tissue", r"kitchen.?roll",
                   r"\bnappies?\b", r"baby.?wipe", r"cotton.?pad",
                   r"cot/wool", r"nutmeg\b",   # Morrisons' own baby/home brand
                   r"colgate", r"toothpaste", r"toothbrush", r"oral.?b",
                   r"lynx\b", r"nivea", r"shower.?gel", r"deodorant",
                   r"durex", r"condom", r"lubricant",
                   r"paracetamol", r"ibuprofen", r"hayfever",
                   r"regina\b", r"blitz\b",    # kitchen paper brands
                   r"\brf\s?powr\b",            # RF Power deodorant/body spray
                   r"shampoo", r"conditioner", r"tresemme",
                   r"\bcandle\b", r"tampon",
                   r"refuse.?sack",
                   r"greeting.?card"]),

    ("fish",    [r"tuna", r"salmon", r"\bcod\b", r"haddock", r"prawn",
                 r"\bfish\b", r"mackerel", r"sardine", r"\bsea\s?bass\b",
                 r"scampi", r"seafood", r"f/finger", r"fish.?finger",
                 r"whitefish"]),

    ("meat",    [r"chicken", r"\bchk\b",   # CHK = chicken (Morrisons abbreviation)
                 r"\bbeef\b", r"\bpork\b", r"\bham\b", r"bacon",
                 r"sausage", r"\bmince\b", r"steak", r"kidney", r"\blamb\b",
                 r"turkey", r"gammon", r"chorizo", r"salami", r"pepperoni",
                 r"meatball", r"\bpie\b", r"hot.?dog", r"black.?pud",
                 r"blk.?pud", r"ye\s?olde\s?oak"]),

    ("dairy",   [r"yogurt", r"yoghurt", r"\byog\b",   # YOG = yoghurt abbreviated
                 r"cheese", r"\bbutter\b", r"margarine", r"\beggs?\b",
                 r"\bcream\b", r"quiche",
                 # cheese varieties / brands
                 r"cheddar", r"mozzarella", r"mzza", r"feta", r"brie",
                 r"stilton", r"gouda", r"edam", r"pecorino", r"parmesan",
                 r"parmigiano", r"reggiano",          # Parmigiano Reggiano
                 r"grana\s?padano", r"ricotta", r"halloumi",
                 r"leicester",                         # Red Leicester
                 r"cathedral", r"pilgrims?\s?choice", r"pilg/choice",
                 r"seriously\s?spreadable", r"philadelphia",
                 r"galbani", r"kerrygold", r"elmlea", r"spreadable",
                 r"tzatziki", r"cheesy.?slice",
                 r"yeo.?val",                          # Yeo Valley yogurts
                 r"red.?fox",                          # Red Fox Red Leicester
                 # drinks
                 r"\bfrijj\b", r"benecol", r"cholesterol.?drink"]),

    ("bakery",  [r"bread", r"naan", r"bagel", r"doughnut", r"rolls?\b",
                 r"croissant", r"crumpet", r"muffin", r"baguette",
                 r"pitta", r"\bbap\b", r"\bbaps\b", r"bloomer", r"loaf",
                 r"split.?tin", r"coburg", r"malties", r"farmhouse",
                 r"hovis\b", r"\bwraps?\b", r"tortilla", r"mission\b",
                 r"deli\s?kitchen", r"sub.?roll", r"\bsub\b",
                 r"hot.cross.bun", r"scone",
                 r"pains?\s+au",                       # pains au chocolat
                 r"pain.au"]),

    ("produce", [r"banana", r"apple", r"onion", r"potato", r"broccoli",
                 r"mushroom", r"melon", r"cabbage", r"carrot", r"tomato",
                 r"pepper", r"lettuce", r"cucumber", r"\bberry\b", r"berries",
                 r"grape", r"orange", r"lemon", r"lime", r"avocado",
                 r"spinach", r"strawberr", r"blueberr", r"raspberr",
                 r"blackberr", r"cherry", r"cherries", r"apricot",
                 r"nectarine", r"mango", r"celery", r"leek", r"swede",
                 r"baby.?corn", r"sweetcorn", r"sweetclem", r"clementine",
                 r"satsuma", r"courgette", r"parsnip", r"broccoli",
                 r"cauliflower", r"garlic", r"ginger", r"\bherb\b", r"basil",
                 r"chive", r"coriander",
                 r"\bpears?\b", r"\bkiwi\b",
                 r"exotic.fruit", r"garden.peas"]),

    ("pasta_rice", [r"pasta", r"rigatoni", r"tortiglioni", r"manfredine",
                    r"spaghetti", r"penne", r"\brice\b", r"noodle",
                    r"lasagne", r"lasgane", r"macaroni", r"fusilli",
                    r"tortell", r"cous.?cous", r"orzo", r"gnocchi",
                    r"barilla"]),

    ("frozen",  [r"mccain", r"hash.?brown", r"pizza\b", r"goodfella",
                 r"ristorante", r"chicago.?town", r"chicage.?town",
                 r"ice.?cre[ae]m", r"\bcones?\b", r"ice.?loll",
                 r"carte.?d.?or", r"lollies", r"lolly",
                 r"chunky.?chips", r"straight.?cut.?chips",
                 r"haagen.?dazs", r"ice.flak"]),

    ("snacks",  [r"doritos", r"belvita", r"mcvitie", r"wispa", r"\bcrisp",
                 r"nachip", r"nachos", r"popcorn", r"pretzel",
                 r"chocolate.?bar", r"choc.?bar", r"flapjack",
                 r"bourbon\b", r"choco.?hoop", r"choco.?nut",
                 r"churros", r"\bdips?\b",
                 # chocolate / confectionery brands
                 r"cadbury", r"haribo", r"terrys?",
                 r"double.?decker", r"\btwirl\b",
                 r"\bjelly\b", r"jelly.babies?",
                 # biscuits / crisps brands
                 r"pringles", r"\bwalkers\b", r"hula.?hoops?",
                 r"hobnob", r"\bdigestive",
                 r"\bcookie", r"\bmaryland\b", r"maynard",
                 r"party.ring", r"\blotus\b", r"\bkipling\b", r"bakewell",
                 # snack packs / nuts / raisins
                 r"raisin", r"\bnuts?\b"]),

    ("drinks_soft", [r"juice", r"\bcola\b", r"lemonade", r"squash",
                     r"\bwater\b", r"\btea\b", r"coffee", r"smoothie",
                     r"starbuck", r"frappuccino", r"tropicana", r"trop\b"]),

    ("cupboard", [r"beans", r"baked.?beans", r"tinned", r"canned",
                  r"chopped.?tom", r"mutti\b", r"polpa",
                  r"stock.?cube", r"\boxo\b", r"batchelor",
                  r"branston", r"ambrosia", r"custard",
                  r"honey", r"jam\b", r"spread\b", r"marmalade",
                  r"peanut.?butter", r"marmite",
                  r"oats?\b", r"porridge", r"muesli", r"cereal",
                  r"corn.?flakes", r"shredd", r"wheat.?biscuit",
                  r"sugar\b", r"flour\b",
                  r"oil\b", r"olive.?oil", r"sunflower.?oil",
                  r"vinegar", r"lentil", r"black.?bean", r"chickpea",
                  r"pesto", r"cooking.?sauce", r"bbq.?sauce",
                  r"mango.?chut", r"mint.?sauce", r"stir.?fry",
                  r"blue.?dragon", r"sharwood", r"patak",
                  r"\bsauce\b", r"\bspice\b", r"paprika", r"cumin",
                  r"masala", r"oregano", r"seasoning",
                  r"couscous", r"cous\s?cous",
                  r"olives?\b", r"kalamata", r"gaea\b",
                  r"chilli\b", r"chili\b",
                  r"curry\b", r"korma", r"tikka", r"keralan",
                  r"ravioli",                   # filled pasta, caught here not pasta_rice
                  r"mushy.?peas", r"coleslaw",
                  r"scioattolo", r"girasole",   # Italian store-cupboard
                  r"\bsoup\b",                  # tinned/carton soups
                  r"mayonnaise", r"mayo\b",
                  r"conserve\b",                # jams/conserves
                  r"\bcinnamon\b", r"turmeric", r"corinader",  # spices (incl. Morrisons typo)
                  r"\bschwartz\b",              # spice brand
                  r"cake.decor"]),              # baking decorations
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
