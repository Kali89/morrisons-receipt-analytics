"""
make_diversity_chart.py  —  shop diversity and standard-order charts.
Run: python make_diversity_chart.py
"""
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
import numpy as np

Path("output").mkdir(exist_ok=True)
df = pd.read_csv("purchases_2026.csv", parse_dates=["date"])
n_shops = df["receipt_id"].nunique()

# ── Classify every item ───────────────────────────────────────────────────
item = (df.groupby(["description","category"])
          .agg(n_shops=("receipt_id","nunique"),
               mean_net=("net","mean"), std_net=("net","std"))
          .reset_index())
item["freq"]  = item["n_shops"] / n_shops
item["cv"]    = (item["std_net"] / item["mean_net"]).fillna(0)

weekly_items      = set(item[(item["freq"] >= 0.60) & (item["cv"] < 0.5)]["description"])
fortnightly_items = set(item[(item["freq"] >= 0.25) & (item["freq"] < 0.60) & (item["cv"] < 0.5)]["description"])

COLOURS = {
    "Weekly staples":      "#2ecc71",
    "Fortnightly staples": "#3498db",
    "Occasional":          "#e67e22",
    "One-off / novel":     "#e74c3c",
}

def classify_item(desc):
    if desc in weekly_items:      return "Weekly staples"
    if desc in fortnightly_items: return "Fortnightly staples"
    return "One-off / novel"

df["item_class"] = df["description"].apply(classify_item)

# ══════════════════════════════════════════════════════════════════════════
# CHART 4 — Stacked bar: per-shop spend by item class (diversity view)
# ══════════════════════════════════════════════════════════════════════════
shop_class = (df.groupby(["receipt_id","date","item_class"])["net"]
                .sum()
                .unstack(fill_value=0.0)
                .reset_index()
                .sort_values("date"))

shop_class["total"] = shop_class[[c for c in COLOURS if c in shop_class.columns]].sum(axis=1)
shop_class["diversity"] = (1 - shop_class.get("Weekly staples", 0) / shop_class["total"]) * 100

fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})
fig.patch.set_facecolor("#FAFAF8")
for ax in axes:
    ax.set_facecolor("#FAFAF8")

fig.suptitle("How varied is each household shop? — spend by item regularity",
             fontsize=15, fontweight="bold", y=1.01, color="#222222")

# ── Top panel: stacked bar ────────────────────────────────────────────────
ax = axes[0]
x     = np.arange(len(shop_class))
dates = [pd.Timestamp(d).strftime("%-d %b") for d in shop_class["date"]]
bottom = np.zeros(len(x))

for cls, colour in COLOURS.items():
    if cls not in shop_class.columns:
        continue
    vals = shop_class[cls].values
    bars = ax.bar(x, vals, bottom=bottom, color=colour,
                  label=cls, edgecolor="white", linewidth=0.8, width=0.7)
    for bar, val in zip(bars, vals):
        if val > 4:
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_y() + val/2,
                    f"£{val:.0f}", ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold")
    bottom += vals

for i, total in enumerate(shop_class["total"]):
    ax.text(i, total + 1.2, f"£{total:.0f}",
            ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#333333")

ax.set_xticks(x)
ax.set_xticklabels(dates, fontsize=9, rotation=30, ha="right")
ax.set_ylabel("£ spent", fontsize=11)
ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("£%.0f"))
ax.spines[["top","right","left"]].set_visible(False)
ax.tick_params(left=False)
ax.grid(axis="y", alpha=0.25, linestyle="--")
ax.set_ylim(0, shop_class["total"].max() * 1.18)
ax.legend(loc="upper left", fontsize=9, framealpha=0, ncol=4)

# ── Bottom panel: diversity score line ───────────────────────────────────
ax2 = axes[1]
ax2.bar(x, shop_class["diversity"], color=[
    "#2ecc71" if d < 60 else "#e67e22" if d < 80 else "#e74c3c"
    for d in shop_class["diversity"]
], edgecolor="white", linewidth=0.8, width=0.7)
ax2.axhline(shop_class["diversity"].mean(), color="#333333",
            linestyle="--", linewidth=1, label=f"Average {shop_class['diversity'].mean():.0f}%")
ax2.set_xticks(x)
ax2.set_xticklabels(dates, fontsize=9, rotation=30, ha="right")
ax2.set_ylabel("Diversity %", fontsize=10)
ax2.set_ylim(0, 115)
ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
ax2.spines[["top","right","left"]].set_visible(False)
ax2.tick_params(left=False)
ax2.grid(axis="y", alpha=0.25, linestyle="--")
ax2.legend(fontsize=9, framealpha=0, loc="upper right")
ax2.set_title("Diversity score per shop  (% of spend on non-staple items)",
              fontsize=10, color="#555555", pad=6)

for i, val in enumerate(shop_class["diversity"]):
    ax2.text(i, val + 2, f"{val:.0f}%", ha="center", va="bottom",
             fontsize=7.5, color="#444444")

plt.tight_layout()
plt.savefig("output/chart4_diversity.png", dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close()
print("Saved: output/chart4_diversity.png")

# ══════════════════════════════════════════════════════════════════════════
# CHART 5 — Item frequency scatter: frequency vs consistency
# ══════════════════════════════════════════════════════════════════════════
item_plot = item[item["freq"] >= 0.15].copy()
item_plot["size"] = item_plot["mean_net"] * 20

fig, ax = plt.subplots(figsize=(13, 8))
fig.patch.set_facecolor("#FAFAF8")
ax.set_facecolor("#FAFAF8")

def item_colour(row):
    if row["freq"] >= 0.60 and row["cv"] < 0.5: return COLOURS["Weekly staples"]
    if row["freq"] >= 0.25 and row["cv"] < 0.5: return COLOURS["Fortnightly staples"]
    return COLOURS["One-off / novel"]

colours = item_plot.apply(item_colour, axis=1)

sc = ax.scatter(item_plot["freq"]*100, item_plot["cv"],
                s=item_plot["size"], c=colours, alpha=0.75,
                edgecolors="white", linewidth=0.8)

# Label every point
for _, r in item_plot.iterrows():
    label = r["description"].replace("M ","").title()
    if len(label) > 22: label = label[:20] + "…"
    ax.annotate(label, (r["freq"]*100, r["cv"]),
                fontsize=7, color="#333333",
                xytext=(4, 3), textcoords="offset points")

# Quadrant guides
ax.axvline(50, color="#aaaaaa", linestyle=":", linewidth=1)
ax.axhline(0.5, color="#aaaaaa", linestyle=":", linewidth=1)
ax.text(51, 1.32, "High frequency\nbut inconsistent spend", fontsize=8,
        color="#888888", va="top")
ax.text(51, -0.06, "STANDARD ORDER\nzone", fontsize=9, fontweight="bold",
        color="#2ecc71", va="bottom")
ax.text(1,  1.32, "Occasional &\nunpredictable", fontsize=8,
        color="#e74c3c", va="top")

legend_patches = [
    mpatches.Patch(color=COLOURS["Weekly staples"],      label="Weekly staple (≥60% freq, CV<0.5)"),
    mpatches.Patch(color=COLOURS["Fortnightly staples"], label="Fortnightly staple (25–59%, CV<0.5)"),
    mpatches.Patch(color=COLOURS["One-off / novel"],     label="Variable / occasional"),
]
ax.legend(handles=legend_patches, fontsize=9, framealpha=0, loc="upper right")

ax.set_xlabel("How often we buy it  (% of shops)", fontsize=11)
ax.set_ylabel("Spend consistency  (CV — lower = more consistent £ per shop)", fontsize=11)
ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
ax.set_xlim(-2, 95)
ax.set_ylim(-0.1, 1.45)
ax.spines[["top","right"]].set_visible(False)
ax.grid(alpha=0.2, linestyle="--")

ax.set_title("Which items are household staples?  Frequency vs spend consistency\n"
             "(bubble size = average spend per shop, 39 shops Feb–Jun 2026)",
             fontsize=13, fontweight="bold", pad=14, color="#222222")

plt.tight_layout()
plt.savefig("output/chart5_item_regularity.png", dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close()
print("Saved: output/chart5_item_regularity.png")


# ══════════════════════════════════════════════════════════════════════════
# CHART 6 — Household milk consumption
# ══════════════════════════════════════════════════════════════════════════
REAL_MILK = ["M BRIT S/SKIM MILK", "M BRITISH WHOLE MILK", "LACTOFREE MILK"]
milk = df[df["description"].isin(REAL_MILK)].copy()
milk["pints"] = milk.apply(
    lambda r: r["quantity"] * (4 if r["unit_price_pence"] == 165 else 3.5), axis=1
)
milk["type"] = milk["description"].apply(
    lambda d: "semi-skim" if "S/SKIM" in d else ("whole" if "WHOLE" in d else "lactofree")
)

TOTAL_WEEKS = (df["date"].max() - df["date"].min()).days / 7
pints_per_week = milk["pints"].sum() / TOTAL_WEEKS

per_shop = (milk.groupby(["receipt_id", "date", "type"])["pints"]
              .sum().reset_index()
              .pivot_table(index=["receipt_id","date"], columns="type",
                           values="pints", fill_value=0)
              .reset_index().sort_values("date"))

milk["month"] = milk["date"].dt.to_period("M")
monthly = milk.groupby(["month", "type"])["pints"].sum().unstack(fill_value=0)

TYPE_C = {"semi-skim": "#3498db", "whole": "#e74c3c", "lactofree": "#27ae60"}

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9),
                                gridspec_kw={"height_ratios": [2, 1]})
fig.patch.set_facecolor("#FAFAF8")
for ax in [ax1, ax2]:
    ax.set_facecolor("#FAFAF8")

fig.suptitle(
    f"Household milk consumption — {pints_per_week:.1f} pints/week  "
    f"({milk['pints'].sum():.0f} pints total, Feb–Jun 2026)",
    fontsize=14, fontweight="bold", y=1.01, color="#222222"
)

# Top panel: per-shop stacked bars
x = np.arange(len(per_shop))
dates = [pd.Timestamp(d).strftime("%-d %b") for d in per_shop["date"]]
bottom = np.zeros(len(x))
for t in ["semi-skim", "whole", "lactofree"]:
    if t not in per_shop.columns:
        continue
    vals = per_shop[t].values
    ax1.bar(x, vals, bottom=bottom, color=TYPE_C[t], label=t.title(),
            edgecolor="white", linewidth=0.6, width=0.75)
    bottom += vals

totals = per_shop[[c for c in TYPE_C if c in per_shop.columns]].sum(axis=1)
for i, total in enumerate(totals):
    if total > 0:
        ax1.text(i, total + 0.2, f"{total:.0f}", ha="center", va="bottom",
                 fontsize=8.5, fontweight="bold", color="#444444")

ax1.set_xticks(x)
ax1.set_xticklabels(dates, rotation=35, ha="right", fontsize=8.5)
ax1.set_ylabel("Pints", fontsize=11)
ax1.spines[["top","right","left"]].set_visible(False)
ax1.tick_params(left=False)
ax1.grid(axis="y", alpha=0.25, linestyle="--")
ax1.legend(loc="upper right", fontsize=10, framealpha=0)
n_milk_shops = int((totals > 0).sum())
ax1.set_title(
    f"Pints bought per shop  (milk purchased in {n_milk_shops} of {n_shops} trips)",
    fontsize=11, color="#555555", pad=6
)

# Bottom panel: monthly totals
xm = np.arange(len(monthly))
bot_m = np.zeros(len(xm))
for t in ["semi-skim", "whole", "lactofree"]:
    if t not in monthly.columns:
        continue
    vals = monthly[t].values
    ax2.bar(xm, vals, bottom=bot_m, color=TYPE_C[t], label=t.title(),
            edgecolor="white", linewidth=0.6, width=0.6)
    bot_m += vals

for i, total in enumerate(monthly.sum(axis=1)):
    ax2.text(i, total + 0.5, f"{total:.0f} pt", ha="center", va="bottom",
             fontsize=10, fontweight="bold", color="#333333")

ax2.set_xticks(xm)
ax2.set_xticklabels(
    [pd.Period(str(m), freq="M").strftime("%b %Y") for m in monthly.index],
    fontsize=10
)
ax2.set_ylabel("Pints/month", fontsize=10)
ax2.spines[["top","right","left"]].set_visible(False)
ax2.tick_params(left=False)
ax2.grid(axis="y", alpha=0.25, linestyle="--")
ax2.set_title("Monthly totals", fontsize=10, color="#555555", pad=6)

plt.tight_layout()
plt.savefig("output/chart6_milk.png", dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close()
print("Saved: output/chart6_milk.png")
print("\nAll charts saved to output/")
