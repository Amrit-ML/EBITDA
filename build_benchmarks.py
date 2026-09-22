"""
build_benchmarks.py

Collapses the long frames download into one row per company-year, joins
industry codes, derives EBITDA and every cost driver as a share of revenue.

USAGE
-----
    python build_benchmarks.py

RESOLUTION RULES
----------------
Several XBRL tags can feed one metric (four different revenue tags, three D&A
tags). Per (company, year, metric) the tag with the lowest `priority` in
fetch_frames.py wins.

EBITDA
------
Not a GAAP tag, so it is derived: operating income + depreciation & amortisation.
Where D&A is not tagged, EBITDA is left blank rather than set equal to EBIT --
quietly treating missing D&A as zero would understate EBITDA for exactly the
capital-heavy companies where the difference matters most.

SG&A vs G&A
-----------
Filers split overhead inconsistently: some tag one combined SG&A line, some tag
G&A and selling/marketing separately, some tag both. `overhead` is therefore
SG&A where reported, else G&A + S&M where both exist. The components are kept
too, so the agent can reason at whichever level a company actually discloses.
"""

import argparse

import numpy as np
import pandas as pd

REVENUE_BANDS = [
    ("<10M", 0, 1e7),
    ("10-50M", 1e7, 5e7),
    ("50-250M", 5e7, 2.5e8),
    ("250M-1B", 2.5e8, 1e9),
    ("1-5B", 1e9, 5e9),
    (">5B", 5e9, float("inf")),
]

# Cost drivers expressed as a share of revenue. Plausible-range clips drop
# reporting artefacts (e.g. a shell with $1k revenue and $2M of G&A) before any
# percentile is taken. They are deliberately generous.
DRIVERS = {
    "ebitda_margin":        ("EBITDA margin", -1.0, 0.8, True),
    "overhead_pct":         ("SG&A (overhead)", 0.0, 1.5, False),
    "ga_pct":               ("G&A", 0.0, 1.0, False),
    "sales_marketing_pct":  ("Sales & marketing", 0.0, 1.0, False),
    "facilities_pct":       ("Facilities (operating lease)", 0.0, 0.5, False),
    "professional_fees_pct": ("Professional & vendor fees", 0.0, 0.5, False),
    "advertising_pct":      ("Advertising (discretionary)", 0.0, 0.6, False),
    "labor_pct":            ("Labor & related", 0.0, 1.5, False),
    "rnd_pct":              ("R&D", 0.0, 2.0, False),
    "capex_pct":            ("CAPEX", 0.0, 1.0, False),
    "share_based_comp_pct": ("Share-based comp", 0.0, 0.5, False),
}


def band_for(revenue):
    if revenue is None or not np.isfinite(revenue) or revenue <= 0:
        return None
    for label, lo, hi in REVENUE_BANDS:
        if lo <= revenue < hi:
            return label
    return REVENUE_BANDS[-1][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="data/frames_panel.csv")
    ap.add_argument("--sic", default="data/sic_map.csv")
    ap.add_argument("--out", default="data/benchmarks.csv")
    args = ap.parse_args()

    long = pd.read_csv(args.frames, encoding="utf-8")
    print(f"read {len(long):,} long rows, {long['cik'].nunique():,} filers")

    # Lowest priority number wins per company-year-metric.
    long = long.sort_values(["cik", "fy", "metric", "priority"])
    picked = long.groupby(["cik", "fy", "metric"], as_index=False).first()

    wide = picked.pivot_table(index=["cik", "fy"], columns="metric",
                              values="value", aggfunc="first").reset_index()
    wide.columns.name = None

    names = (long.sort_values("fy").groupby("cik", as_index=False)
             .last()[["cik", "entity_name"]])
    wide = wide.merge(names, on="cik", how="left")

    sic = pd.read_csv(args.sic, encoding="utf-8", dtype={"sic2": str})
    wide = wide.merge(sic[["cik", "sic", "sic2", "major_group", "division"]],
                      on="cik", how="left")
    matched = wide["sic"].notna().mean()
    print(f"company-years with an industry code: {matched:.1%}")

    for col in DRIVERS_SOURCE_COLS:
        if col not in wide.columns:
            wide[col] = np.nan

    # Overhead: combined SG&A where tagged, else the two components summed.
    wide["overhead"] = wide["sga"]
    both = wide["overhead"].isna() & wide["ga"].notna() & wide["sales_marketing"].notna()
    wide.loc[both, "overhead"] = wide.loc[both, "ga"] + wide.loc[both, "sales_marketing"]
    wide["overhead_source"] = np.where(
        wide["sga"].notna(), "sga_reported",
        np.where(both, "ga_plus_sm", ""))

    # EBITDA only where D&A is actually known. See module docstring.
    wide["ebitda"] = wide["operating_income"] + wide["depreciation_amortization"]

    rev = wide["revenue"].where(wide["revenue"] > 0)
    wide["ebitda_margin"] = wide["ebitda"] / rev
    wide["overhead_pct"] = wide["overhead"] / rev
    wide["ga_pct"] = wide["ga"] / rev
    wide["sales_marketing_pct"] = wide["sales_marketing"] / rev
    wide["facilities_pct"] = wide["facilities"] / rev
    wide["professional_fees_pct"] = wide["professional_fees"] / rev
    wide["advertising_pct"] = wide["advertising"] / rev
    wide["labor_pct"] = wide["labor"] / rev
    wide["rnd_pct"] = wide["rnd"] / rev
    wide["capex_pct"] = wide["capex"] / rev
    wide["share_based_comp_pct"] = wide["share_based_comp"] / rev

    wide["revenue_band"] = wide["revenue"].apply(band_for)
    wide["has_revenue"] = wide["revenue"].fillna(0) > 0

    # Drop the current, incomplete fiscal year if few have filed yet.
    counts = wide.groupby("fy")["cik"].nunique()
    partial = counts[counts < 0.3 * counts.max()].index.tolist()
    if partial:
        print(f"dropping incomplete fiscal year(s) {partial}")
        wide = wide[~wide["fy"].isin(partial)]

    wide = wide.sort_values(["cik", "fy"])
    wide.to_csv(args.out, index=False, encoding="utf-8")

    r = wide[wide["has_revenue"]]
    print(f"\nwrote {len(wide):,} company-years -> {args.out}")
    print(f"  filers           : {wide['cik'].nunique():,}")
    print(f"  fiscal years     : {int(wide['fy'].min())}-{int(wide['fy'].max())}")
    print(f"  with revenue     : {len(r):,}")
    print(f"  with EBITDA      : {int(r['ebitda'].notna().sum()):,}")
    print("\nusable values per driver (revenue-bearing, in plausible range):")
    for key, (label, lo, hi, _) in DRIVERS.items():
        n = int(r[key].between(lo, hi).sum())
        print(f"  {label:30s} {n:6,}")


DRIVERS_SOURCE_COLS = [
    "revenue", "operating_income", "net_income", "depreciation_amortization",
    "cost_of_revenue", "sga", "ga", "sales_marketing", "rnd", "facilities",
    "advertising", "professional_fees", "labor", "share_based_comp", "capex",
    "assets",
]


if __name__ == "__main__":
    main()
