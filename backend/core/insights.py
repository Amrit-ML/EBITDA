"""Insights: eight productivity and overhead ratios against a benchmark.

The ratios come from the P&L, its periods, and the headcount the user enters
(a P&L has no headcount line). Each is compared with a benchmark: in
percentage points for ratios that are themselves percentages, and in percent
for dollar figures, where "percentage points" has no meaning.

The BENCHMARKS below are PLACEHOLDERS, as requested for this stage. The two
SG&A ratios are rounded from real SEC peer medians (revenue over $100M) so the
examples look realistic; the rest are illustrative. Every response says so,
and the UI labels them, so no one mistakes them for measured peer data.

Everything here is arithmetic; no model is called.
"""

from __future__ import annotations

from typing import Optional

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


# Missing-value messages that the UI can act on, and the action for each: the
# card offers a button rather than leaving the user to work out what to do.
NO_FTE = "Add total employees"
NO_SGA_FTE = "Add SG&A employees"
REUPLOAD = "Needs SG&A by period, which this P&L was saved without"
ACTIONS = {NO_FTE: "add_total_fte", NO_SGA_FTE: "add_sga_fte", REUPLOAD: "reupload"}


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

    Needs at least two periods with both SG&A and revenue. A trend saved
    before SG&A was recorded per period has no `sga` series and says so.
    """
    if not trend or len(trend.get("periods", [])) < 2:
        return None, "Needs a P&L with two or more periods"
    sga, rev = trend.get("sga"), trend.get("revenue")
    if not sga or not rev:
        return None, REUPLOAD
    pairs = [(s, r) for s, r in zip(sga, rev) if s is not None and r is not None]
    if len(pairs) < 2:
        return None, "Needs SG&A and revenue in two or more periods"
    g_sga = _growth(pairs[0][0], pairs[-1][0])
    g_rev = _growth(pairs[0][1], pairs[-1][1])
    if g_sga is None or g_rev is None:
        return None, "Growth cannot be measured from a zero or negative start"
    return (g_sga - g_rev) * 100, None


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

    no_fte = NO_FTE
    no_sga = "Needs G&A and sales & marketing lines"
    no_gp = "Needs a cost of revenue line"
    values: dict[str, tuple[Optional[float], Optional[str]]] = {
        "sga_pct_revenue": (_div(sga, revenue), None if sga is not None else no_sga),
        "sga_pct_gross_profit": (
            _div(sga, gross_profit) if gross_profit and gross_profit > 0 else None,
            no_sga if sga is None else (no_gp if gross_profit is None
                                        else "Gross profit is not positive")),
        "sga_growth_vs_revenue_growth": _sga_growth_gap(trend),
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
    rows = []
    for key, label, formula, kind, lower_is_better in METRICS:
        value, missing = values[key]
        b = bench[key]
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
            # "pp" for shares and growth gaps, "%" for dollar figures.
            "difference": diff,
            "difference_unit": "%" if kind == "usd" else "pp",
            "favourable": (None if diff is None or abs(diff) < 1e-9
                           else (diff < 0) == lower_is_better),
            "missing": None if value is not None else missing,
            # What would fill the gap: add_total_fte, add_sga_fte, reupload.
            "action": None if value is not None else ACTIONS.get(missing),
        })

    basis = None
    if trend and len(trend.get("periods", [])) >= 2:
        basis = f"{trend['periods'][0]} to {trend['periods'][-1]}"
    return {
        "industry": industry,
        "benchmarks_are_placeholder": True,
        "headcount": {"total_fte": fte, "sga_fte": sga_fte},
        "growth_basis": basis,
        "metrics": rows,
    }
