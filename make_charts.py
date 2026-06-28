"""
make_charts.py
--------------
Produce shareable spend charts from purchases_2026.csv.
Saves PNGs to output/.

Run: python make_charts.py
"""

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

Path("output").mkdir(exist_ok=True)

df = pd.read_csv("purchases_2026.csv", parse_dates=["date"])

df_norm = df
norm_weeks = (df_norm["date"].max() - df_norm["date"].min()).days / 7

# ── Palette ────────────────────────────────────────────────────────────────
PALETTE = {
    "Fresh & protein":   "#4C72B0",
    "Fruit & veg":       "#55A868",
    "Bread & bakery":    "#C9A84C",
    "Everyday staples":  "#8172B3",
    "Treats & leisure":  "#C44E52",
    "Household & personal": "#937860",
}

FREQ_PALETTE = {
    "Every shop":   "#2ecc71",
    "Most shops":   "#3498db",
    "Sometimes":    "#e67e22",
    "Occasionally": "#e74c3c",
}

# ── Groupings ──────────────────────────────────────────────────────────────
MEAL_GROUPS = {
    "Fresh & protein":      ["dairy", "milk", "meat", "fish"],
    "Fruit & veg":          ["produce"],
    "Bread & bakery":       ["bakery"],
    "Everyday staples":     ["pasta_rice", "cupboard"],
    "Treats & leisure":     ["snacks", "alcohol", "drinks_soft", "frozen"],
    "Household & personal": ["household"],
}

FREQ_GROUPS = {
    "Every shop":   ["bakery", "dairy", "produce"],              # 85–90%
    "Most shops":   ["milk", "cupboard", "meat", "household"],   # 72–79%
    "Sometimes":    ["snacks", "pasta_rice", "frozen"],          # 44–59%
    "Occasionally": ["alcohol", "fish", "drinks_soft"],          # 21–28%
}

# Friendly display names for individual categories
CAT_LABELS = {
    "dairy":        "Cheese, cream\n& eggs",
    "milk":         "Milk",
    "meat":         "Meat",
    "fish":         "Fish",
    "produce":      "Fruit & veg",
    "bakery":       "Bread & bakery",
    "pasta_rice":   "Pasta & rice",
    "cupboard":     "Tins, sauces\n& staples",
    "snacks":       "Snacks",
    "alcohol":      "Alcohol",
    "drinks_soft":  "Soft drinks",
    "frozen":       "Frozen",
    "household":    "Household &\npersonal care",
}

def group_spend(source_df, weeks, groups):
    cat_pw = source_df.groupby("category")["net"].sum() / weeks
    result = {}
    for grp, cats in groups.items():
        result[grp] = sum(cat_pw.get(c, 0) for c in cats)
    return pd.Series(result)


# ══════════════════════════════════════════════════════════════════════════
# CHART 1 — Pie + bar: "Where does the weekly shop money go?"
# ══════════════════════════════════════════════════════════════════════════
grp_pw = group_spend(df_norm, norm_weeks, MEAL_GROUPS)
cat_pw = df_norm.groupby("category")["net"].sum() / norm_weeks

fig, axes = plt.subplots(1, 2, figsize=(14, 7))
fig.patch.set_facecolor("#FAFAF8")
for ax in axes:
    ax.set_facecolor("#FAFAF8")

fig.suptitle(
    "Household Morrisons spend — where the money goes",
    fontsize=16, fontweight="bold", y=1.01, color="#222222"
)
fig.text(0.5, 0.97, "Average week, Feb–Jun 2026  ·  £87/wk household total  ·  39 shops across both More Card accounts",
         ha="center", fontsize=10, color="#666666")

# — Pie —
ax_pie = axes[0]
colors = [PALETTE[g] for g in grp_pw.index]
wedges, texts, autotexts = ax_pie.pie(
    grp_pw.values,
    labels=None,
    autopct=lambda p: f"£{p*grp_pw.sum()/100:.2f}\n({p:.0f}%)",
    colors=colors,
    startangle=140,
    pctdistance=0.72,
    wedgeprops=dict(linewidth=1.5, edgecolor="white"),
)
for at in autotexts:
    at.set_fontsize(9)
    at.set_color("white")
    at.set_fontweight("bold")

legend_labels = [f"{g}  (£{v:.2f}/wk)" for g, v in grp_pw.items()]
ax_pie.legend(wedges, legend_labels, loc="lower center",
              bbox_to_anchor=(0.5, -0.18), fontsize=9,
              framealpha=0, ncol=2)
ax_pie.set_title(f"Total: £{grp_pw.sum():.2f} / week", fontsize=12,
                 pad=12, color="#333333")

# — Horizontal bar (individual categories, grouped by colour) —
ax_bar = axes[1]
cat_order = []
bar_colors = []
for grp, cats in MEAL_GROUPS.items():
    for c in cats:
        if cat_pw.get(c, 0) > 0:
            cat_order.append(c)
            bar_colors.append(PALETTE[grp])

vals  = [cat_pw.get(c, 0) for c in cat_order]
ylabels = [CAT_LABELS.get(c, c) for c in cat_order]

y = np.arange(len(cat_order))
bars = ax_bar.barh(y, vals, color=bar_colors, height=0.6,
                   edgecolor="white", linewidth=0.8)
ax_bar.set_yticks(y)
ax_bar.set_yticklabels(ylabels, fontsize=9)
ax_bar.invert_yaxis()
ax_bar.set_xlabel("£ per week", fontsize=10)
ax_bar.xaxis.set_major_formatter(mticker.FormatStrFormatter("£%.0f"))
ax_bar.spines[["top", "right", "left"]].set_visible(False)
ax_bar.tick_params(left=False)
ax_bar.grid(axis="x", alpha=0.3, linestyle="--")

for bar, val, cat in zip(bars, vals, cat_order):
    ax_bar.text(val + 0.15, bar.get_y() + bar.get_height() / 2,
                f"£{val:.2f}", va="center", fontsize=8.5,
                color="#444444",
                fontweight="bold" if cat == "dairy" else "normal")
# Callout for dairy — the top single category
dairy_y = cat_order.index("dairy") if "dairy" in cat_order else None
if dairy_y is not None:
    ax_bar.annotate("  ← #1 category",
                    xy=(cat_pw.get("dairy", 0), dairy_y),
                    xytext=(cat_pw.get("dairy", 0) * 0.55, dairy_y - 0.55),
                    fontsize=8, color="#4C72B0", fontstyle="italic",
                    arrowprops=dict(arrowstyle="-", color="#4C72B0", lw=0.8))

# Group dividers
pos = 0
for grp, cats in MEAL_GROUPS.items():
    visible = [c for c in cats if cat_pw.get(c, 0) > 0]
    if visible:
        ax_bar.axhline(pos - 0.5, color="#cccccc", linewidth=0.8, linestyle=":")
        pos += len(visible)

ax_bar.set_xlim(0, max(vals) * 1.25)
ax_bar.set_title("Breakdown by item", fontsize=12, pad=12, color="#333333")

plt.tight_layout()
plt.savefig("output/chart1_weekly_breakdown.png", dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close()
print("Saved: output/chart1_weekly_breakdown.png")


# ══════════════════════════════════════════════════════════════════════════
# CHART 2 — Stacked bar: monthly spend by group
# ══════════════════════════════════════════════════════════════════════════
monthly_cat = (df.set_index("date")
                 .groupby([pd.Grouper(freq="ME"), "category"])["net"]
                 .sum()
                 .unstack(fill_value=0.0))

monthly_grp = pd.DataFrame(index=monthly_cat.index)
for grp, cats in MEAL_GROUPS.items():
    monthly_grp[grp] = monthly_cat[[c for c in cats if c in monthly_cat.columns]].sum(axis=1)

fig, ax = plt.subplots(figsize=(12, 6))
fig.patch.set_facecolor("#FAFAF8")
ax.set_facecolor("#FAFAF8")

month_labels = [d.strftime("%b\n%Y") for d in monthly_grp.index]
x = np.arange(len(month_labels))
bottom = np.zeros(len(x))

for grp in MEAL_GROUPS:
    vals = monthly_grp[grp].values
    bars = ax.bar(x, vals, bottom=bottom, label=grp,
                  color=PALETTE[grp], edgecolor="white", linewidth=0.8, width=0.6)
    for bar, val in zip(bars, vals):
        if val > 8:
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_y() + val / 2,
                    f"£{val:.0f}", ha="center", va="center",
                    fontsize=7.5, color="white", fontweight="bold")
    bottom += vals

# Annotate total on top of each bar
for i, total in enumerate(monthly_grp.sum(axis=1)):
    ax.text(i, total + 4, f"£{total:.0f}", ha="center", va="bottom",
            fontsize=10, fontweight="bold", color="#333333")

ax.set_xticks(x)
ax.set_xticklabels(month_labels, fontsize=11)
ax.set_ylabel("£ spent", fontsize=11)
ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("£%.0f"))
ax.spines[["top", "right", "left"]].set_visible(False)
ax.tick_params(left=False)
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.set_ylim(0, monthly_grp.sum(axis=1).max() * 1.15)

ax.legend(loc="upper left", fontsize=9, framealpha=0, ncol=3)
ax.set_title("Household monthly Morrisons spend by category  (Feb–Jun 2026)",
             fontsize=14, fontweight="bold", pad=14, color="#222222")
fig.text(0.5, -0.02,
         "April (11 shops) and June (8 shops, big household restock + wine offers) were the busiest months",
         ha="center", fontsize=9, color="#888888", style="italic")

plt.tight_layout()
plt.savefig("output/chart2_monthly_trend.png", dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close()
print("Saved: output/chart2_monthly_trend.png")


# ══════════════════════════════════════════════════════════════════════════
# CHART 3 — Frequency donut: regular staples vs occasional vs treats
# ══════════════════════════════════════════════════════════════════════════
freq_pw = {}
for freq_grp, cats in FREQ_GROUPS.items():
    freq_pw[freq_grp] = sum(cat_pw.get(c, 0) for c in cats)
freq_series = pd.Series(freq_pw)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.patch.set_facecolor("#FAFAF8")
for ax in axes:
    ax.set_facecolor("#FAFAF8")

fig.suptitle("How often does the household buy each type of thing?",
             fontsize=16, fontweight="bold", y=1.02, color="#222222")
fig.text(0.5, 0.97, "Left: weekly spend share by purchase frequency  ·  Right: how often each category appears in a shop  (39 shops, Feb–Jun 2026)",
         ha="center", fontsize=10, color="#666666")

# — Donut pie —
ax_donut = axes[0]
colors_freq = [FREQ_PALETTE[g] for g in freq_series.index]
wedges, _, autotexts = ax_donut.pie(
    freq_series.values,
    labels=None,
    autopct=lambda p: f"£{p*freq_series.sum()/100:.2f}\n({p:.0f}%)",
    colors=colors_freq,
    startangle=90,
    pctdistance=0.78,
    wedgeprops=dict(width=0.55, linewidth=1.5, edgecolor="white"),
)
for at in autotexts:
    at.set_fontsize(9.5)
    at.set_color("white")
    at.set_fontweight("bold")

ax_donut.text(0, 0, f"£{freq_series.sum():.2f}\n/week", ha="center", va="center",
              fontsize=12, fontweight="bold", color="#333333")

legend_patches = [
    plt.Rectangle((0,0),1,1, color=FREQ_PALETTE[g], label=f"{g}  (£{v:.2f}/wk)")
    for g, v in freq_series.items()
]
ax_donut.legend(handles=legend_patches, loc="lower center",
                bbox_to_anchor=(0.5, -0.15), fontsize=9, framealpha=0, ncol=2)

freq_labels_detail = {
    "Every shop":   "85–90% of shops",
    "Most shops":   "72–79% of shops",
    "Sometimes":    "44–59% of shops",
    "Occasionally": "21–28% of shops",
}
ax_donut.set_title("Spend split by how often we buy it", fontsize=11, pad=12, color="#333333")

# — Horizontal bar: frequency per category —
ax_freq = axes[1]
freq_pct = {
    "bakery": 90, "produce": 90, "dairy": 85,
    "milk": 79, "cupboard": 77, "meat": 72, "household": 72,
    "snacks": 59, "pasta_rice": 49, "frozen": 44,
    "alcohol": 28, "drinks_soft": 23, "fish": 21,
}

def freq_color(pct):
    if pct >= 85: return FREQ_PALETTE["Every shop"]
    if pct >= 70: return FREQ_PALETTE["Most shops"]
    if pct >= 45: return FREQ_PALETTE["Sometimes"]
    return FREQ_PALETTE["Occasionally"]

sorted_cats = sorted(freq_pct, key=freq_pct.get, reverse=True)
freq_vals = [freq_pct[c] for c in sorted_cats]
freq_colors = [freq_color(v) for v in freq_vals]
freq_ylabels = [CAT_LABELS.get(c, c) for c in sorted_cats]

y2 = np.arange(len(sorted_cats))
bars2 = ax_freq.barh(y2, freq_vals, color=freq_colors, height=0.6,
                     edgecolor="white", linewidth=0.8)
ax_freq.set_yticks(y2)
ax_freq.set_yticklabels(freq_ylabels, fontsize=9)
ax_freq.invert_yaxis()
ax_freq.set_xlabel("% of shops where we buy this", fontsize=10)
ax_freq.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
ax_freq.spines[["top", "right", "left"]].set_visible(False)
ax_freq.tick_params(left=False)
ax_freq.grid(axis="x", alpha=0.3, linestyle="--")
ax_freq.set_xlim(0, 115)

for bar, val, cat in zip(bars2, freq_vals, sorted_cats):
    pw = cat_pw.get(cat, 0)
    ax_freq.text(val + 1.5, bar.get_y() + bar.get_height() / 2,
                 f"{val}%  ·  £{pw:.2f}/wk", va="center", fontsize=8.5, color="#444444")

freq_legend = [
    plt.Rectangle((0,0),1,1, color=FREQ_PALETTE[g], label=f"{g} ({d})")
    for g, d in freq_labels_detail.items()
]
ax_freq.legend(handles=freq_legend, loc="lower right", fontsize=8.5, framealpha=0)
ax_freq.set_title("Purchase frequency per category", fontsize=11, pad=12, color="#333333")

plt.tight_layout()
plt.savefig("output/chart3_frequency.png", dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close()
print("Saved: output/chart3_frequency.png")
print("\nAll charts saved to output/")
