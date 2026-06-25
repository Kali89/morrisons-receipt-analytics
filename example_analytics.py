"""
example_analytics.py
--------------------
Once `parse_many` + `apply_categories` have given you one tidy DataFrame for the
year, your four questions are short groupby/resample one-liners. This file shows
the patterns; adapt freely. (You know pandas — this is here to connect the dots,
not to teach.)

Assumed input `df` columns (from the pipeline):
    date (datetime), description, category,
    quantity, net_pence, net (£), gross, discount, ...
Each row is one line item on one receipt.
"""

from __future__ import annotations

import pandas as pd


def spend_over_time(df: pd.DataFrame, freq: str = "W") -> pd.Series:
    """Total net spend per period. freq='W' weekly, 'ME' monthly, 'D' daily."""
    return df.set_index("date")["net"].resample(freq).sum()


def category_over_time(df: pd.DataFrame, category: str, freq: str = "W") -> pd.Series:
    """Net spend on one category per period (e.g. category='milk')."""
    sub = df.loc[df["category"] == category]
    return sub.set_index("date")["net"].resample(freq).sum()


def category_matrix(df: pd.DataFrame, freq: str = "ME") -> pd.DataFrame:
    """Period x category spend table — handy for a stacked area/bar chart."""
    return (df.set_index("date")
              .groupby([pd.Grouper(freq=freq), "category"])["net"].sum()
              .unstack(fill_value=0.0))


def trend(series: pd.Series, window: int = 4) -> pd.DataFrame:
    """Pair a spend series with its rolling mean to read the direction of travel."""
    return pd.DataFrame({"spend": series, f"rolling_{window}": series.rolling(window).mean()})


if __name__ == "__main__":
    import json
    from pathlib import Path

    from parse_receipts import parse_receipt
    from categorise import apply_categories, build_mapping

    # In reality you'd parse_many() across the year; one receipt here just to run.
    df, _ = parse_receipt(json.loads(Path("full_receipt.json").read_text()),
                          receipt_id="demo-001", date="2026-01-14")
    mapping = build_mapping(df["description"], cache_path="category_map.json")
    df = apply_categories(df, mapping)

    print("Q: how much on milk this week?")
    print(category_over_time(df, "milk", freq="W"), "\n")

    print("Q: how much on meat?")
    print(category_over_time(df, "meat", freq="W"), "\n")

    print("Q: how much on alcohol?  (none in this basket -> empty series)")
    print(category_over_time(df, "alcohol", freq="W"), "\n")

    print("Q: total spend over time (monthly)?")
    print(spend_over_time(df, freq="ME"))
