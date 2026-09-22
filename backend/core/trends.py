"""Multi-period EBITDA trend analysis over an uploaded P&L.

This is the structured-data counterpart to core/rag.py. A file with several
periods across its columns already carries a time series; core/ingest.extract
only ever pulls one period out of it, so the shape of the business over time is
discarded at the point of upload. This module keeps it.

Everything here is arithmetic. The driver attribution in particular is a ranked
contribution calculation, not a model call: the same philosophy the rest of the
app follows, where figures are computed in code and the model supplies judgment
only.
"""

from __future__ import annotations

import re
from typing import Optional

from core import companies, ingest

# Cost lines considered when attributing a move in EBITDA. `overhead` is left
# out on purpose -- it is the sum of G&A and sales & marketing, so including it
# would count the same dollars twice and hand back a phantom driver.
_COST_FIELDS = ("cost_of_revenue", "ga", "sales_marketing", "rnd",
                "facilities", "advertising", "professional_fees")

_FIELD_LABEL = {
    "revenue": "revenue",
    "cost_of_revenue": "cost of revenue",
    "ga": "G&A",
    "sales_marketing": "sales & marketing",
    "rnd": "R&D",
    "facilities": "facilities",
    "advertising": "advertising",
    "professional_fees": "professional fees",
}

_QUARTER = re.compile(r"\bq\s*([1-4])\b", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def period_sort_key(label: str) -> tuple:
    """Order periods by calendar time, not by the order the columns happen to sit in.

    Real exports arrive with periods in any order -- newest-first is common in
    board packs. Sorting on the label as a string puts "Q10" before "Q2" and
    "FY2019" before "FY9"; sorting on the parsed year and sub-period does not.
    Anything unparseable sorts last but keeps its relative position, so a file
    with no recognisable periods is left in file order rather than scrambled.
    """
    text = str(label)
    year = ingest.year_in(text)
    if year is None:
        return (1, 0, 0, text)
    q = _QUARTER.search(text)
    if q:
        return (0, year, int(q.group(1)), text)
    low = text.lower()
    for name, num in _MONTHS.items():
        if name in low:
            # Months are mapped onto quarter-thirds so monthly and quarterly
            # columns in the same file still interleave in calendar order.
            return (0, year, num / 3.0, text)
    return (0, year, 0, text)


def _ebitda(values: dict) -> Optional[float]:
    """EBITDA for one period, derived exactly as the rest of the app derives it."""
    fin = companies.normalise_financials(values)
    return fin.get("ebitda")


def series(upload_id: str, mapping: dict, units: str = "dollars") -> list[dict]:
    """Every period in the upload, chronologically, with its financials."""
    up = ingest._UPLOADS.get(upload_id)
    if up is None:
        raise ValueError("Upload not found - it may have expired when the "
                         "server restarted. Upload the file again.")

    periods = up.get("periods", [])
    keys = [p["key"] for p in periods]
    if not keys:
        raise ValueError("No periods were detected in this file.")

    # An annual or "Total" column beside the quarters it sums is not a period.
    # Left in, FY2025 sorted ahead of Q1 2025 and the trend read "revenue came
    # down $352.8M between FY2025 and Q4" -- the year compared with a quarter.
    years_with_subperiods = {p.get("year") for p in periods
                             if ingest._is_subperiod(p["key"])}
    year_of = {p["key"]: p.get("year") for p in periods}
    def keep(k: str) -> bool:
        if "total" in k.lower():
            return False
        if ingest._is_subperiod(k):
            return True
        # An annual column stands only when that year has no quarters/months.
        return year_of.get(k) not in years_with_subperiods

    keys = [k for k in keys if keep(k)]
    if not keys:
        raise ValueError("No periods were detected in this file.")

    rows = []
    for key in sorted(keys, key=period_sort_key):
        # Each period stands alone here; annualising a quarter would turn every
        # point in the series into the same year total.
        extracted = ingest.extract(upload_id, mapping, key, units,
                                   annualise=False)
        fin = companies.normalise_financials(extracted["financials"])
        rows.append({
            "period": key,
            "financials": fin,
            "ebitda": fin.get("ebitda"),
            "revenue": fin.get("revenue"),
        })
    return rows


def _drivers(first: dict, last: dict) -> list[dict]:
    """Cost lines ranked by how much each moved EBITDA between two periods.

    A fall in a cost line lifts EBITDA, so its contribution is the negative of
    its change; revenue contributes with its own sign.
    """
    out = []
    rev_a, rev_b = first.get("revenue"), last.get("revenue")
    if rev_a is not None and rev_b is not None:
        out.append({"field": "revenue", "label": _FIELD_LABEL["revenue"],
                    "change_usd": rev_b - rev_a,
                    "contribution_usd": rev_b - rev_a})
    for f in _COST_FIELDS:
        a, b = first.get(f), last.get(f)
        if a is None or b is None:
            continue
        out.append({"field": f, "label": _FIELD_LABEL.get(f, f),
                    "change_usd": b - a, "contribution_usd": -(b - a)})
    out.sort(key=lambda d: abs(d["contribution_usd"]), reverse=True)
    return out


def _commentary(periods: list[str], values: list[float], average: float,
                current: float, variance_pct: Optional[float],
                drivers: list[dict], currency_scale: float = 1e6) -> str:
    def m(v):
        return f"${v / currency_scale:,.1f}M"

    first, last = periods[0], periods[-1]

    # Plain wording throughout: this text is read by operators, not analysts.
    # "usual level" says what the average IS for; the average deliberately
    # excludes the current period, so it really is the level before now.
    if variance_pct is None:
        opening = f"EBITDA was {m(current)} in {last}. Your usual level is {m(average)}."
    elif current >= average:
        opening = (f"EBITDA was {m(current)} in {last}. That is about "
                   f"{abs(variance_pct):.0f}% better than your usual "
                   f"{m(average)}.")
    else:
        opening = (f"EBITDA was {m(current)} in {last}. That is about "
                   f"{abs(variance_pct):.0f}% below your usual "
                   f"{m(average)}.")
    lines = [opening]

    if drivers:
        top = drivers[0]
        moved = "grew" if top["change_usd"] > 0 else "came down"
        effect = "which helped" if top["contribution_usd"] > 0 else "which hurt"
        lines.append(
            f"The main reason is {top['label']}, which {moved} "
            f"{m(abs(top['change_usd']))} between {first} and {last}, {effect}.")
        second = next((d for d in drivers[1:]
                       if abs(d["contribution_usd"]) > 0), None)
        if second:
            s_moved = "also grew" if second["change_usd"] > 0 else "also came down"
            s_effect = ("which added to the gain" if second["contribution_usd"] > 0
                        else "which cancelled out some of that")
            lines.append(
                f"{second['label'].capitalize()} {s_moved} "
                f"{m(abs(second['change_usd']))}, {s_effect}.")

    return " ".join(lines[:3])


def analyse(upload_id: str, mapping: dict, units: str = "dollars") -> dict:
    """The whole analysis: series, averages, variance, chart data, commentary."""
    rows = series(upload_id, mapping, units)
    priced = [r for r in rows if r["ebitda"] is not None]
    if not priced:
        raise ValueError(
            "EBITDA could not be derived for any period. Map either an EBITDA "
            "line, or operating income together with depreciation & "
            "amortisation.")

    periods = [r["period"] for r in priced]
    values = [float(r["ebitda"]) for r in priced]

    current = values[-1]
    # The average is of the PRIOR periods, not of everything: including the
    # current period in its own benchmark pulls the average toward it and
    # shrinks the very variance the comparison exists to show.
    history = values[:-1]
    historical_average = sum(history) / len(history) if history else current
    all_average = sum(values) / len(values)
    variance_pct = (((current - historical_average) / abs(historical_average))
                    * 100 if historical_average else None)

    drivers = _drivers(priced[0]["financials"], priced[-1]["financials"])

    return {
        "periods": periods,
        "ebitda": values,
        "revenue": [r["revenue"] for r in priced],
        # SG&A per period (G&A + sales & marketing, or a stated SG&A line),
        # for Insights' "SG&A growth vs revenue growth".
        "sga": [r["financials"].get("overhead") for r in priced],
        "current_period": periods[-1],
        "current_ebitda": current,
        "historical_average": historical_average,
        "series_average": all_average,
        "variance_pct": variance_pct,
        "variance_usd": current - historical_average,
        "drivers": drivers,
        "commentary": _commentary(periods, values, historical_average, current,
                                  variance_pct, drivers),
        "chart": {
            "type": "bar",
            "x": {"field": "period", "values": periods},
            "y": {"field": "ebitda", "values": values, "unit": "USD"},
            "series": [
                {"name": "EBITDA", "type": "bar", "data": [
                    {"period": p, "value": v} for p, v in zip(periods, values)]},
                {"name": "Historical average", "type": "line",
                 "constant": historical_average},
            ],
        },
    }
