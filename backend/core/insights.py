"""Insights: eight productivity and overhead ratios against a benchmark.

The ratios come from the P&L, its periods, and the headcount the user enters
(a P&L has no headcount line). Each is compared with a benchmark: in
percentage points for ratios that are themselves percentages, and in percent
for dollar figures, where "percentage points" has no meaning.

Peer figures come from two places, and every row says which:
  - "damodaran": Aswath Damodaran's US margins by industry (NYU Stern,
    data/damodaran_margins.csv, built by build_damodaran.py). It has SG&A and
    gross margin, so it supplies SG&A % revenue and SG&A % gross profit.
  - "example": placeholder figures for the six ratios no public source covers
    (growth, and everything per employee). The UI labels them as examples.

Everything here is arithmetic; no model is called.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from typing import Optional

import config
from core import companies

# key: (label, formula, kind, lower_is_better)
#   kind "pct": a share, compared in percentage points
#   kind "pp":  already a difference of two growth rates, compared in points
#   kind "usd": a dollar amount, compared in percent
METRICS = [
    ("sga_pct_revenue", "SG&A % Revenue", "SG&A ÷ Revenue", "pct", True),
    ("sga_pct_gross_profit", "SG&A % Gross Profit", "SG&A ÷ Gross Profit", "pct", True),
    ("sga_growth_vs_revenue_growth", "SG&A Growth vs Revenue Growth",
     "SG&A growth % − revenue growth %", "pp", True),
    ("sga_per_employee", "SG&A $ / Employee", "SG&A ÷ total FTE", "usd", True),
    ("revenue_per_employee", "Revenue / Employee", "Revenue ÷ FTE", "usd", False),
    ("gross_profit_per_employee", "Gross Profit / Employee", "Gross Profit ÷ FTE", "usd", False),
    ("ebitda_per_employee", "EBITDA / Employee", "EBITDA ÷ FTE", "usd", False),
    ("sga_fte_pct", "SG&A FTE %", "SG&A FTE ÷ total FTE", "pct", True),
]

@lru_cache(maxsize=1)
def damodaran() -> dict:
    """industry -> Damodaran's row, or {} when the file has not been built."""
    try:
        with open(config.DAMODARAN_PATH, encoding="utf-8") as fh:
            return {r["industry"]: r for r in csv.DictReader(fh)}
    except FileNotFoundError:
        return {}


def _damodaran_benchmarks(industry: str) -> dict[str, float]:
    row = damodaran().get(industry)
    if not row:
        return {}
    sga, gross = float(row["sga_pct_revenue"]), float(row["gross_margin"])
    out = {"sga_pct_revenue": sga}
    if gross > 0:
        # SG&A / gross profit = (SG&A / sales) / (gross profit / sales).
        out["sga_pct_gross_profit"] = sga / gross
    return out


def source_note(industry: str) -> Optional[str]:
    row = damodaran().get(industry)
    if not row:
        return None
    return (f"Damodaran, NYU Stern: US {row['source_industry']}, "
            f"{row['firms']} companies, {row['as_of']}")


PLACEHOLDER_BENCHMARKS = {
    "pharma": {
        "sga_pct_revenue": 0.32,
        "sga_pct_gross_profit": 0.53,
        "sga_growth_vs_revenue_growth": 0.0,
        "sga_per_employee": 140_000,
        "revenue_per_employee": 550_000,
        "gross_profit_per_employee": 380_000,
        "ebitda_per_employee": 90_000,
        "sga_fte_pct": 0.28,
    },
    "biotech": {
        "sga_pct_revenue": 0.51,
        "sga_pct_gross_profit": 0.58,
        "sga_growth_vs_revenue_growth": 0.0,
        "sga_per_employee": 150_000,
        "revenue_per_employee": 450_000,
        "gross_profit_per_employee": 360_000,
        "ebitda_per_employee": 40_000,
        "sga_fte_pct": 0.24,
    },
}


# What to do about an unfavourable ratio: where to look, why it matters, and a
# first step. Opportunities only -- no savings or dollar gaps (owner decision,
# 2026-09-22). Written for a CEO or deal team, not an accountant.
IMPROVEMENTS = {
    "sga_pct_revenue": {
        "area": "Overhead cost base",
        "why": "Overhead takes a larger share of each revenue dollar than it does "
               "across the industry.",
        "first_step": "Split SG&A by function (finance, HR, IT, legal, commercial) "
                      "and compare each with last year to find where the growth sits.",
    },
    "sga_pct_gross_profit": {
        "area": "Overhead against margin",
        "why": "Overhead absorbs more of gross profit than the industry, leaving "
               "less to fund R&D and earnings.",
        "first_step": "Check whether the cause is overhead or margin: review "
                      "pricing and cost of goods alongside the largest SG&A lines.",
    },
    "sga_growth_vs_revenue_growth": {
        "area": "Overhead growth",
        "why": "SG&A is growing faster than revenue, so overhead is scaling ahead "
               "of the business.",
        "first_step": "List the SG&A hires and contracts added this year and check "
                      "which were tied to growth plans that have not yet delivered.",
    },
    "sga_per_employee": {
        "area": "Non-headcount overhead",
        "why": "Overhead cost per employee is above the industry, which points to "
               "vendors, software and facilities rather than salaries.",
        "first_step": "Review the vendor register and software licences for "
                      "duplicate tools and contracts that can be consolidated.",
    },
    "revenue_per_employee": {
        "area": "Workforce productivity",
        "why": "Each employee generates less revenue than the industry.",
        "first_step": "Compare headcount growth with revenue growth by function and "
                      "review open roles where output has not grown.",
    },
    "gross_profit_per_employee": {
        "area": "Margin per employee",
        "why": "Each employee generates less gross profit than the industry.",
        "first_step": "Separate the two causes, margin (pricing, cost of goods) and "
                      "headcount, and address the larger one first.",
    },
    "ebitda_per_employee": {
        "area": "Earnings per employee",
        "why": "Earnings per employee trail the industry.",
        "first_step": "Review management layers and spans of control, together "
                      "with the overhead actions above.",
    },
    "sga_fte_pct": {
        "area": "Organisation design",
        "why": "A larger share of staff sits in SG&A functions than across the "
               "industry.",
        "first_step": "Map SG&A roles by function and site to find duplicated teams "
                      "and work that can be centralised or automated.",
    },
}


def _gap_size(kind: str, diff: float, benchmark: float) -> float:
    """How far off the industry a ratio is, on one scale for ranking: a share
    of the industry figure. A growth gap has no base, so its points count as
    percent."""
    if kind == "pct":
        return abs(diff) / (abs(benchmark) * 100) if benchmark else abs(diff) / 100
    return abs(diff) / 100


# Missing-value messages that the UI can act on, and the action for each: the
# card offers a button rather than leaving the user to work out what to do.
NO_FTE = "Add total employees"
NO_SGA_FTE = "Add SG&A employees"
REUPLOAD = "Needs SG&A by period, which this P&L was saved without"
ACTIONS = {NO_FTE: "add_total_fte", NO_SGA_FTE: "add_sga_fte", REUPLOAD: "reupload"}

# Differences are shown to one decimal. A gap that rounds to 0.0 is level:
# calling it better or worse would put a verdict on a chip that reads "0.0".
LEVEL_WITHIN = 0.05


def _div(a, b) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _growth(first, last) -> Optional[float]:
    if first is None or last is None or first <= 0:
        return None
    return (last - first) / first


def _sga_growth_gap(trend: Optional[dict]):
    """SG&A growth minus revenue growth, first period to latest, in points.

    Returns (gap, missing, parts): parts holds the two growth rates behind
    the gap, so a reader can see why it is what it is.

    Needs at least two periods with both SG&A and revenue. A trend saved
    before SG&A was recorded per period has no `sga` series and says so.
    """
    if not trend or len(trend.get("periods", [])) < 2:
        return None, "Needs a P&L with two or more periods", None
    sga, rev = trend.get("sga"), trend.get("revenue")
    if not sga or not rev:
        return None, REUPLOAD, None
    pairs = [(s, r) for s, r in zip(sga, rev) if s is not None and r is not None]
    if len(pairs) < 2:
        return None, "Needs SG&A and revenue in two or more periods", None
    g_sga = _growth(pairs[0][0], pairs[-1][0])
    g_rev = _growth(pairs[0][1], pairs[-1][1])
    if g_sga is None or g_rev is None:
        return None, "Growth cannot be measured from a zero or negative start", None
    return (g_sga - g_rev) * 100, None, {"sga_growth": g_sga, "revenue_growth": g_rev}


def compute(company: dict, industry: str) -> dict:
    # Derived exactly as the benchmark derives it: SG&A from G&A + S&M when
    # no SG&A line is given, EBITDA from operating income + D&A.
    fin = companies.normalise_financials(company.get("financials", {}))
    head = company.get("headcount") or {}
    fte, sga_fte = head.get("total_fte"), head.get("sga_fte")

    revenue = fin.get("revenue")
    cogs = fin.get("cost_of_revenue")
    gross_profit = revenue - cogs if revenue is not None and cogs is not None else None
    sga = fin.get("overhead")
    ebitda = fin.get("ebitda")
    trend = company.get("trend")
    growth_gap, growth_missing, growth_parts = _sga_growth_gap(trend)

    no_fte = NO_FTE
    no_sga = "Needs G&A and sales & marketing lines"
    no_gp = "Needs a cost of revenue line"
    values: dict[str, tuple[Optional[float], Optional[str]]] = {
        "sga_pct_revenue": (_div(sga, revenue), None if sga is not None else no_sga),
        "sga_pct_gross_profit": (
            _div(sga, gross_profit) if gross_profit and gross_profit > 0 else None,
            no_sga if sga is None else (no_gp if gross_profit is None
                                        else "Gross profit is not positive")),
        "sga_growth_vs_revenue_growth": (growth_gap, growth_missing),
        "sga_per_employee": (_div(sga, fte), no_fte if not fte else no_sga),
        "revenue_per_employee": (_div(revenue, fte), no_fte),
        "gross_profit_per_employee": (_div(gross_profit, fte),
                                      no_fte if not fte else no_gp),
        "ebitda_per_employee": (_div(ebitda, fte),
                                no_fte if not fte else "Needs EBITDA, or operating income with D&A"),
        "sga_fte_pct": (_div(sga_fte, fte),
                        no_fte if not fte else NO_SGA_FTE),
    }

    bench = PLACEHOLDER_BENCHMARKS.get(industry, PLACEHOLDER_BENCHMARKS["pharma"])
    real = _damodaran_benchmarks(industry)
    rows = []
    for key, label, formula, kind, lower_is_better in METRICS:
        value, missing = values[key]
        b = real.get(key, bench[key])
        diff = None
        if value is not None:
            if kind == "pct":
                diff = (value - b) * 100          # percentage points
            elif kind == "pp":
                diff = value - b                  # already in points
            else:
                diff = (value - b) / abs(b) * 100 if b else None   # percent
        rows.append({
            "key": key,
            "label": label,
            "formula": formula,
            "kind": kind,
            "lower_is_better": lower_is_better,
            "value": value,
            "benchmark": b,
            "benchmark_source": "damodaran" if key in real else "example",
            # "pp" for shares and growth gaps, "%" for dollar figures.
            "difference": diff,
            "difference_unit": "%" if kind == "usd" else "pp",
            "favourable": (None if diff is None or abs(diff) < LEVEL_WITHIN
                           else (diff < 0) == lower_is_better),
            "missing": None if value is not None else missing,
            # What would fill the gap: add_total_fte, add_sga_fte, reupload.
            "action": None if value is not None else ACTIONS.get(missing),
            # The two growth rates behind the growth gap (fractions); null
            # for every other ratio.
            "parts": (growth_parts if key == "sga_growth_vs_revenue_growth"
                      and value is not None else None),
        })

    # Unfavourable ratios, largest gap first, each with where to look and a
    # first step.
    improvements = sorted(
        ({"key": r["key"], "label": r["label"], "difference": r["difference"],
          "difference_unit": r["difference_unit"], **IMPROVEMENTS[r["key"]],
          "_size": _gap_size(r["kind"], r["difference"], r["benchmark"])}
         for r in rows if r["favourable"] is False),
        key=lambda i: -i["_size"])
    for i in improvements:
        del i["_size"]

    basis = None
    if trend and len(trend.get("periods", [])) >= 2:
        basis = f"{trend['periods'][0]} to {trend['periods'][-1]}"
    return {
        "industry": industry,
        # True while any row still uses an example figure.
        "benchmarks_are_placeholder": any(r["benchmark_source"] == "example" for r in rows),
        "benchmark_source_note": source_note(industry),
        "headcount": {"total_fte": fte, "sga_fte": sga_fte},
        "growth_basis": basis,
        "metrics": rows,
        "improvements": improvements,
    }
