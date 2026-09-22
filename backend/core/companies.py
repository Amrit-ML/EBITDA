"""P&L registry: the synthetic sample P&Ls plus anything uploaded.

Everything the UI benchmarks or diagnoses is a company here, so the rest of the
app never needs to know whether figures came from a demo or a file.

Uploaded companies live in memory and are lost when the backend restarts.
"""

import uuid
from typing import Optional

from core.industries import is_valid, label_for
from core.portcos import PORTCOS

_UPLOADED: dict = {}


def normalise_financials(fin: dict) -> dict:
    """Fill derivable lines the same way build_benchmarks.py does for peers.

    Subject and peers must be derived identically or the comparison is
    invalid: SG&A from G&A + S&M when not given, EBITDA from operating income
    + D&A when not given. EBITDA is never assumed equal to operating income
    when D&A is unknown.
    """
    f = {k: v for k, v in fin.items() if v is not None}
    if "overhead" not in f and "ga" in f and "sales_marketing" in f:
        f["overhead"] = f["ga"] + f["sales_marketing"]
    if ("ebitda" not in f and "operating_income" in f
            and "depreciation_amortization" in f):
        f["ebitda"] = f["operating_income"] + f["depreciation_amortization"]
    return f


def create_uploaded(name: Optional[str], industry: str, fiscal_year: int,
                    financials: dict, source: str = "") -> dict:
    fin = normalise_financials(financials)
    revenue = fin.get("revenue")
    if not revenue or revenue <= 0:
        raise ValueError("Revenue is required and must be positive to "
                         "benchmark the company.")
    if not is_valid(industry):
        raise ValueError("Industry must be 'biotech' or 'pharma'.")

    cid = "upload-" + uuid.uuid4().hex[:8]
    company = {
        "id": cid,
        # Users never name their company; the field survives only so an API
        # caller can label an upload if it wants to.
        "name": ((name or "").strip() or "Your company")[:80],
        "tagline": f"Uploaded from {source}" if source else "Uploaded P&L",
        "industry": industry,
        "fiscal_year": int(fiscal_year),
        "synthetic": False,
        "uploaded": True,
        "financials": fin,
        "adjustments": [],
        "planted": {},
        "hidden_facts": {},
    }
    _UPLOADED[cid] = company
    return company


def restore_uploaded(company: dict) -> None:
    """Put a saved upload back in memory (core/history.py, at startup)."""
    if company.get("id"):
        _UPLOADED[company["id"]] = company


def get(company_id: str) -> Optional[dict]:
    return PORTCOS.get(company_id) or _UPLOADED.get(company_id)


# --- EBITDA history ------------------------------------------------------------
#
# A P&L upload is a snapshot; the question "how are we holding up" needs the
# snapshots kept. Without this every upload started from nothing, so there was
# never a prior period to average against and the comparison could not exist.
#
# History is held per company and survives repeated uploads against the same
# company, so each new period is measured against everything recorded before it.

def record_periods(company_id: str, entries: list) -> list:
    """Add or update periods in a company's EBITDA history.

    `entries` are {"period": str, "ebitda": float, "revenue": float|None}.
    Re-recording a period replaces it rather than appending a duplicate, so
    uploading a corrected file does not double-count the quarter.
    """
    c = get(company_id)
    if c is None:
        raise ValueError(f"Unknown company '{company_id}'.")
    hist = c.setdefault("ebitda_history", [])
    by_period = {h["period"]: h for h in hist}
    for e in entries:
        period = str(e.get("period") or "").strip()
        ebitda = e.get("ebitda")
        if not period or ebitda is None:
            continue
        by_period[period] = {"period": period, "ebitda": float(ebitda),
                             "revenue": e.get("revenue")}
    from core.trends import period_sort_key
    c["ebitda_history"] = sorted(by_period.values(),
                                 key=lambda h: period_sort_key(h["period"]))
    return c["ebitda_history"]


def ebitda_history(company_id: str) -> dict:
    """The recorded periods, with the average of everything before the latest.

    The average excludes the current period on purpose: a period included in
    its own benchmark drags the average toward itself and hides the very
    movement the comparison is meant to show.
    """
    c = get(company_id)
    if c is None:
        raise ValueError(f"Unknown company '{company_id}'.")
    hist = list(c.get("ebitda_history") or [])
    periods = [h["period"] for h in hist]
    values = [h["ebitda"] for h in hist]

    if not values:
        return {"periods": [], "ebitda": [], "count": 0,
                "current_period": None, "current_ebitda": None,
                "historical_average": None, "variance_pct": None,
                "variance_usd": None, "status": "no data",
                "message": "No periods recorded yet."}

    current = values[-1]
    prior = values[:-1]
    if not prior:
        return {"periods": periods, "ebitda": values, "count": len(values),
                "current_period": periods[-1], "current_ebitda": current,
                "historical_average": None, "variance_pct": None,
                "variance_usd": None, "status": "baseline",
                "message": ("First period recorded. Add another period to see "
                            "how this one compares.")}

    average = sum(prior) / len(prior)
    variance_pct = ((current - average) / abs(average) * 100) if average else None
    if variance_pct is None:
        status = "flat"
    elif variance_pct >= 5:
        status = "ahead"
    elif variance_pct <= -5:
        status = "behind"
    else:
        status = "in line"

    def m(v):
        return f"${v / 1e6:.1f}M"

    if status == "ahead":
        msg = (f"{periods[-1]} came in at {m(current)}, about "
               f"{abs(variance_pct):.0f}% better than your usual {m(average)}.")
    elif status == "behind":
        msg = (f"{periods[-1]} came in at {m(current)}, about "
               f"{abs(variance_pct):.0f}% below your usual {m(average)}.")
    else:
        msg = (f"{periods[-1]} came in at {m(current)}, about level with your "
               f"usual {m(average)}.")

    return {"periods": periods, "ebitda": values, "count": len(values),
            "current_period": periods[-1], "current_ebitda": current,
            "historical_average": average, "variance_pct": variance_pct,
            "variance_usd": current - average, "status": status,
            "message": msg}


def in_industry(company: dict, industry: str) -> dict:
    """The same P&L, benchmarked against the industry the user selected.

    Industry is the user's choice, not a property of the file: they pick it
    first and may change it after uploading. Returns a view; the stored
    company is unchanged.
    """
    if not is_valid(industry):
        raise ValueError("Industry must be 'biotech' or 'pharma'.")
    return {**company, "industry": industry}


def get_adjusted_ebitda(c: dict) -> Optional[float]:
    ebitda = c.get("financials", {}).get("ebitda")
    if ebitda is None:
        return None
    return ebitda + sum(a.get("amount", 0) for a in c.get("adjustments", []))


def add_adjustment(company_id: str, description: str, amount: float, driver: str) -> Optional[dict]:
    c = get(company_id)
    if not c:
        return None
    if "adjustments" not in c:
        c["adjustments"] = []
    c["adjustments"].append({
        "id": uuid.uuid4().hex[:8],
        "description": description,
        "amount": amount,
        "driver": driver
    })
    return c


def summary(c: dict) -> dict:
    return {
        "id": c["id"], "name": c["name"], "tagline": c["tagline"],
        "industry": c["industry"], "industry_label": label_for(c["industry"]),
        "fiscal_year": c["fiscal_year"], "synthetic": c.get("synthetic", False),
        "uploaded": c.get("uploaded", False),
        "revenue": c["financials"].get("revenue"),
        "adjustments": c.get("adjustments", []),
        "adjusted_ebitda": get_adjusted_ebitda(c),
    }


def list_all() -> list:
    return ([summary(p) for p in PORTCOS.values()]
            + [summary(u) for u in _UPLOADED.values()])
