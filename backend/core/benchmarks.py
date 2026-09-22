"""Peer selection and deterministic cost comparison.

Every number the agent is allowed to cite is produced here, in code. The model
reasons about which gaps are structural and interviews the user; it never
computes a benchmark or sizes a saving itself.

Two industries only, Biotechnology and Pharmaceutical (core/industries.py).
Peers never widen beyond them: a drug company benchmarked against software or
machinery filers is not being compared with anything meaningful.
"""

from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd

import config
from core.drivers import (CASH, DRIVERS, GROWTH, LEVER, LEVER_OVERLAP,
                          OUTCOME, ROLLUP)
from core.industries import INDUSTRIES, label_for

REVENUE_BANDS = [
    ("<10M", 0, 1e7),
    ("10-50M", 1e7, 5e7),
    ("50-250M", 5e7, 2.5e8),
    ("250M-1B", 2.5e8, 1e9),
    ("1-5B", 1e9, 5e9),
    (">5B", 5e9, float("inf")),
]
BAND_LABELS = [b[0] for b in REVENUE_BANDS]
# Peers start at PEER_MIN_REVENUE, so the lowest band never holds any. A
# company in it is compared with the nearest band that does, and says so.
PEER_BANDS = [b for b, lo, hi in REVENUE_BANDS if hi > config.PEER_MIN_REVENUE]

_PANEL: Optional[pd.DataFrame] = None


def band_for(revenue):
    if revenue is None or not np.isfinite(revenue) or revenue <= 0:
        return None
    for label, lo, hi in REVENUE_BANDS:
        if lo <= revenue < hi:
            return label
    return BAND_LABELS[-1]


def load_panel(path=None, map_path=None) -> pd.DataFrame:
    global _PANEL
    if _PANEL is not None:
        return _PANEL
    path = path or config.BENCHMARKS_PATH
    map_path = map_path or config.INDUSTRY_MAP_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Benchmarks not found at {path}. Run fetch_frames.py, "
            f"build_sic_map.py and build_benchmarks.py first.")
    if not map_path.exists():
        raise FileNotFoundError(
            f"Industry map not found at {map_path}. Run build_industry_map.py.")

    df = pd.read_csv(path, encoding="utf-8", low_memory=False)
    if len(df) < config.EXPECTED_MIN_ROWS:
        raise ValueError(f"{path} has {len(df)} rows; expected "
                         f">= {config.EXPECTED_MIN_ROWS}. Rebuild it.")
    if df["cik"].nunique() < config.EXPECTED_MIN_FILERS:
        raise ValueError(f"{path} has too few filers. Rebuild it.")

    imap = pd.read_csv(map_path, encoding="utf-8")[["cik", "industry"]]
    df = df.merge(imap, on="cik", how="inner")
    df = df[df["has_revenue"].astype(bool)
            & (df["revenue"] >= config.PEER_MIN_REVENUE)
            & df["industry"].isin(INDUSTRIES)].copy()
    if df["cik"].nunique() < config.EXPECTED_MIN_INDUSTRY_FILERS:
        raise ValueError(f"Only {df['cik'].nunique()} biotech/pharma filers "
                         f"after filtering. Rebuild the industry map.")
    _PANEL = df
    return _PANEL


def reset_cache():
    global _PANEL
    _PANEL = None
    industries.cache_clear()
    reference_year.cache_clear()


@lru_cache(maxsize=1)
def reference_year() -> int:
    """Latest fiscal year with near-complete filing coverage.

    A year still being filed holds fewer filers, and the missing ones skew
    towards slower, smaller filers. Anchoring the industry view there would
    quietly shift its peer mix.
    """
    counts = load_panel().groupby("fy")["cik"].nunique()
    return int(counts[counts >= 0.9 * counts.max()].index.max())


def pooled_years(fiscal_year: int) -> list:
    return list(range(fiscal_year - config.POOL_YEARS + 1, fiscal_year + 1))


@lru_cache(maxsize=1)
def industries() -> list:
    """The two industries with their recent peer counts."""
    df = load_panel()
    recent = df[df["fy"].isin(pooled_years(reference_year()))]
    return [{"id": key, "label": spec["label"],
             "description": spec["description"],
             "filers": int(recent.loc[recent["industry"] == key, "cik"].nunique())}
            for key, spec in INDUSTRIES.items()]


def _adjacent(band, spread=1):
    if band is None:
        return None
    i = BAND_LABELS.index(band)
    return BAND_LABELS[max(0, i - spread): min(len(BAND_LABELS), i + spread + 1)]


def peer_candidates(industry: str, band: Optional[str], fiscal_year: int):
    """Yield (frame, relaxations, level) from tightest to widest.

    Starts from pooled recent years, never a single year. Each step lists
    exactly the relaxations it applies (not a running total), so the UI can say
    precisely how a peer set was built.
    """
    if industry not in INDUSTRIES:
        raise ValueError(f"Unknown industry '{industry}'.")
    df = load_panel()
    recent = pooled_years(fiscal_year)
    all_years = sorted(df["fy"].unique())
    b0 = [band] if band else None
    near = _adjacent(band)

    same = {"industry": industry}
    steps = [("industry", same, b0, recent, [])]
    steps.append(("industry", same, b0, all_years, ["pooled_all_years"]))
    if band:
        steps += [
            ("industry", same, near, recent, ["adjacent_revenue_bands"]),
            ("industry", same, near, all_years,
             ["adjacent_revenue_bands", "pooled_all_years"]),
        ]
    steps.append(("drugs", {}, b0, recent, ["broadened_to_biotech_and_pharma"]))
    steps.append(("drugs", {}, near, all_years,
                  ["broadened_to_biotech_and_pharma", "pooled_all_years"]
                  + (["adjacent_revenue_bands"] if band else [])))

    for level, filt, bands, years, relax in steps:
        out = df
        for col, val in filt.items():
            out = out[out[col] == val]
        if bands is not None:
            out = out[out["revenue_band"].isin(bands)]
        out = out[out["fy"].isin(years)]
        yield out, relax, level


def _confidence(n: int, level: str, relaxations=()) -> str:
    """How much weight a comparison deserves.

    Same-industry, same-size peers in quantity are high confidence. Mixing in
    neighbouring size bands caps it at medium: cost ratios move a lot with
    scale. Mixing biotech with pharma is low regardless of n; their cost
    structures differ (biotech R&D runs at several times pharma's).
    """
    if level == "drugs":
        return "low"
    if n >= 50 and "adjacent_revenue_bands" not in relaxations:
        return "high"
    return "medium"


def driver_peers(driver_key: str, industry: str, band, fiscal_year: int,
                 min_peers: Optional[int] = None) -> dict:
    """Widen until this driver has enough usable values."""
    spec = DRIVERS[driver_key]
    min_peers = min_peers or config.MIN_PEERS
    last = None
    for frame, relax, level in peer_candidates(industry, band, fiscal_year):
        vals = frame[driver_key].dropna() if driver_key in frame else pd.Series(dtype=float)
        kept = vals[(vals >= spec.clip_low) & (vals <= spec.clip_high)]
        last = (kept, relax, level, frame)
        if len(kept) >= min_peers:
            break
    kept, relax, level, frame = last
    return {
        "values": kept,
        "relaxations": relax,
        "industry_level": level,
        "companies": int(frame.loc[kept.index, "cik"].nunique()) if len(kept) else 0,
        "enough": len(kept) >= min_peers,
    }


def percentile_of(value: float, arr: pd.Series) -> float:
    a = arr.to_numpy(dtype=float)
    return 100.0 * ((a < value).sum() + 0.5 * (a == value).sum()) / len(a)


def compare_driver(driver_key: str, company: dict, industry: str,
                   fiscal_year: int) -> dict:
    """Benchmark one driver and size its opportunity."""
    spec = DRIVERS[driver_key]
    revenue = company.get("revenue")
    band = band_for(revenue)

    raw = company.get(spec.source)
    value = (raw / revenue) if (raw is not None and revenue) else None

    base = {
        "driver": driver_key,
        "label": spec.label,
        "ebitda_role": spec.ebitda_role,
        "lower_is_better": spec.lower_is_better,
        "company_value": value,
        "company_dollars": raw,
    }

    peers = driver_peers(driver_key, industry, band, fiscal_year)
    vals = peers["values"]
    common = {
        "n": int(len(vals)),
        "peer_companies": peers["companies"],
        "relaxations": peers["relaxations"],
        "industry_level": peers["industry_level"],
    }

    if not peers["enough"]:
        return {**base, **common, "available": False,
                "confidence": "insufficient",
                "reason": f"only {len(vals)} comparable filers report this"}

    p25, med, p75 = (float(vals.quantile(0.25)), float(vals.median()),
                     float(vals.quantile(0.75)))
    stats = {"p25": p25, "median": med, "p75": p75,
             "confidence": _confidence(len(vals), peers["industry_level"],
                                       peers["relaxations"])}

    if value is None:
        return {**base, **common, **stats, "available": False,
                "reason": "not in the company's data"}

    pct = percentile_of(value, vals)
    # The efficient end is p25 for a cost and p75 for a margin.
    top_quartile = p25 if spec.lower_is_better else p75

    result = {**base, **common, **stats, "available": True,
              "percentile": round(pct, 1),
              "top_quartile_target": top_quartile}

    if spec.lower_is_better and spec.ebitda_role in (LEVER, LEVER_OVERLAP, CASH):
        result["gap_to_median_usd"] = max(0.0, (value - med) * revenue)
        result["gap_to_top_quartile_usd"] = max(0.0, (value - p25) * revenue)
        result["above_median"] = value > med
    return result


def compare_company(company: dict, industry: str, fiscal_year: int) -> dict:
    """Full deterministic comparison plus a correctly-built total.

    The total sums only independent EBITDA levers. Overlapping levers widen an
    upper bound, rollups are excluded, and cash levers are reported separately
    as free cash flow -- see core/drivers.py for why.
    """
    rows = [compare_driver(k, company, industry, fiscal_year) for k in DRIVERS]
    by = {r["driver"]: r for r in rows}

    def gap(r, which):
        return r.get(which, 0.0) if r.get("available") else 0.0

    def stretch_gap(r):
        # A top-quartile target is only meaningful over a dense, same-industry,
        # same-size peer set. On a thin or widened distribution p25 swings
        # wildly -- a thin test case once produced a +33-point margin "upside"
        # -- so below high confidence the stretch case falls back to the median.
        if r.get("confidence") == "high":
            return gap(r, "gap_to_top_quartile_usd")
        return gap(r, "gap_to_median_usd")

    levers = [r for r in rows if r["ebitda_role"] == LEVER]
    overlap = [r for r in rows if r["ebitda_role"] == LEVER_OVERLAP]
    cash = [r for r in rows if r["ebitda_role"] == CASH]

    ebitda_low = sum(gap(r, "gap_to_median_usd") for r in levers)
    ebitda_high = (sum(stretch_gap(r) for r in levers)
                   + sum(stretch_gap(r) for r in overlap))

    revenue = company.get("revenue")
    ebitda = by["ebitda_margin"].get("company_dollars")

    return {
        "company": {
            "revenue": revenue,
            "revenue_band": band_for(revenue),
            "industry": industry,
            "industry_label": label_for(industry),
            "fiscal_year": fiscal_year,
            "peer_years": pooled_years(fiscal_year),
            "ebitda": ebitda,
            "ebitda_margin": by["ebitda_margin"].get("company_value"),
        },
        "drivers": rows,
        "totals": {
            # These are BENCHMARK GAPS -- the distance to peers -- not savings a
            # company can bank. How much of a gap is structural and addressable
            # is what the diagnostic interview establishes.
            "nature": "benchmark_gap_not_committed_savings",
            "ebitda_gap_low_usd": ebitda_low,
            "ebitda_gap_high_usd": ebitda_high,
            "low_basis": "independent EBITDA levers closed to peer median",
            "high_basis": ("independent levers to top quartile where peer data "
                           "is high-confidence (median otherwise), plus "
                           "facilities, which may partly overlap G&A"),
            "cash_opportunity_usd": sum(gap(r, "gap_to_top_quartile_usd")
                                        for r in cash),
            "cash_basis": "CAPEX to top quartile; free cash flow, not EBITDA",
            "margin_gap_low_pts": (100 * ebitda_low / revenue) if revenue else None,
            "margin_gap_high_pts": (100 * ebitda_high / revenue) if revenue else None,
            "excluded": {
                "rollups": [r["label"] for r in rows if r["ebitda_role"] == ROLLUP],
                "growth_protected": [r["label"] for r in rows
                                     if r["ebitda_role"] == GROWTH],
                "outcome": [r["label"] for r in rows if r["ebitda_role"] == OUTCOME],
            },
        },
    }


def industry_profile(industry: str, band: Optional[str] = None,
                     fiscal_year: Optional[int] = None) -> dict:
    """What an industry spends on each cost driver -- no company needed.

    Uses exactly the peer selection a company comparison would, so the medians
    shown here are the ones an uploaded P&L is later ranked against. `band`
    None means every size (from PEER_MIN_REVENUE up).
    """
    if industry not in INDUSTRIES:
        raise ValueError(f"Unknown industry '{industry}'.")
    if band is not None and band not in PEER_BANDS:
        raise ValueError(f"Unknown revenue band '{band}'.")

    df = load_panel()
    fy = fiscal_year or reference_year()
    years = pooled_years(fy)
    group = df[(df["industry"] == industry) & df["fy"].isin(years)]
    in_scope = group if band is None else group[group["revenue_band"] == band]

    drivers = []
    for key, spec in DRIVERS.items():
        peers = driver_peers(key, industry, band, fy)
        vals = peers["values"]
        row = {
            "driver": key,
            "label": spec.label,
            "ebitda_role": spec.ebitda_role,
            "lower_is_better": spec.lower_is_better,
            "description": spec.description,
            "n": int(len(vals)),
            "peer_companies": peers["companies"],
            "relaxations": peers["relaxations"],
            "industry_level": peers["industry_level"],
            "available": peers["enough"],
        }
        if peers["enough"]:
            row.update({
                "p10": float(vals.quantile(0.10)),
                "p25": float(vals.quantile(0.25)),
                "median": float(vals.median()),
                "p75": float(vals.quantile(0.75)),
                "p90": float(vals.quantile(0.90)),
                "confidence": _confidence(len(vals), peers["industry_level"],
                                          peers["relaxations"]),
            })
        else:
            row.update({"confidence": "insufficient",
                        "reason": f"only {len(vals)} comparable filers report this"})
        drivers.append(row)

    revenue = in_scope["revenue"].dropna()
    return {
        "id": industry,
        "label": label_for(industry),
        "description": INDUSTRIES[industry]["description"],
        "band": band,
        "fiscal_year": fy,
        "years": years,
        "min_revenue": config.PEER_MIN_REVENUE,
        "filers": int(in_scope["cik"].nunique()),
        "company_years": int(len(in_scope)),
        "median_revenue": float(revenue.median()) if len(revenue) else None,
        "bands": [{"band": b,
                   "filers": int(group.loc[group["revenue_band"] == b, "cik"].nunique())}
                  for b in PEER_BANDS],
        "drivers": drivers,
    }
