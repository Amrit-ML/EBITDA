"""Engine correctness tests.

The agent cites only numbers this engine produces, so these guard the things a
finance audience would catch: double-counted totals, CAPEX counted as EBITDA,
growth investment recommended as a cut, stretch targets built on noise, and
peers drawn from outside biotech and pharma.
"""

import pandas as pd
import pytest

import config
from core import benchmarks as bm
from core.drivers import CASH, DRIVERS, GROWTH, ROLLUP
from core.portcos import PORTCOS


@pytest.fixture(scope="module")
def results():
    return {
        pid: bm.compare_company(p["financials"], p["industry"], p["fiscal_year"])
        for pid, p in PORTCOS.items()
    }


def by_driver(res):
    return {d["driver"]: d for d in res["drivers"]}


# --- data + primitives -------------------------------------------------------

def test_panel_is_biotech_and_pharma_only():
    df = bm.load_panel()
    assert set(df["industry"]) == {"biotech", "pharma"}
    assert df["cik"].nunique() >= config.EXPECTED_MIN_INDUSTRY_FILERS
    imap = pd.read_csv(config.INDUSTRY_MAP_PATH)
    assert set(df["cik"]) <= set(imap["cik"]), "every peer comes from the lists"


def test_pre_commercial_companies_are_not_peers():
    df = bm.load_panel()
    assert (df["revenue"] >= config.PEER_MIN_REVENUE).all()
    assert "<10M" not in set(df["revenue_band"])
    assert "<10M" not in bm.PEER_BANDS


@pytest.mark.parametrize("rev,band", [
    (None, None), (0, None), (5e6, "<10M"), (1e7, "10-50M"),
    (1.8e8, "50-250M"), (4.2e8, "250M-1B"), (2e9, "1-5B"), (9e9, ">5B"),
])
def test_band_for(rev, band):
    assert bm.band_for(rev) == band


def test_percentile_midpoint_ties():
    assert bm.percentile_of(5.0, pd.Series([5.0] * 4)) == 50.0


def test_unknown_industry_raises():
    with pytest.raises(ValueError):
        bm.compare_company({"revenue": 1e8}, "software", 2025)


# --- the demo actually works -------------------------------------------------

@pytest.mark.parametrize("pid", list(PORTCOS))
def test_planted_problems_are_found(results, pid):
    """Every planted inefficiency must land in the worst quartile of peers."""
    drivers = by_driver(results[pid])
    for key in PORTCOS[pid]["planted"]:
        d = drivers[key]
        assert d["available"], f"{pid}: {key} unavailable"
        assert d["percentile"] >= 75, (
            f"{pid}: planted {key} only at percentile {d['percentile']}")


def test_pharma_sample_primary_demo_values(results):
    d = by_driver(results["pharma-sample"])
    assert d["ga_pct"]["company_value"] == pytest.approx(0.20)
    assert d["facilities_pct"]["company_value"] == pytest.approx(0.021)
    assert d["ga_pct"]["gap_to_median_usd"] > 20e6


def test_biotech_sample_rnd_is_above_median_but_never_a_gap(results):
    """R&D is the biotech sample's largest line and above median, on purpose."""
    rnd = by_driver(results["biotech-sample"])["rnd_pct"]
    assert rnd["percentile"] > 50
    assert "gap_to_median_usd" not in rnd


def test_sample_fiscal_year_is_the_reference_year():
    """So the industry view and a loaded sample show the same peer years."""
    assert {p["fiscal_year"] for p in PORTCOS.values()} == {bm.reference_year()}


# --- totals are built correctly ---------------------------------------------

@pytest.mark.parametrize("pid", list(PORTCOS))
def test_growth_drivers_never_counted(results, pid):
    """R&D and S&M are benchmarked but must never inflate the EBITDA prize."""
    res = results[pid]
    for d in res["drivers"]:
        assert "gap_to_median_usd" not in d or d["ebitda_role"] != GROWTH
    assert "Sales & marketing" in res["totals"]["excluded"]["growth_protected"]
    assert "R&D" in res["totals"]["excluded"]["growth_protected"]


@pytest.mark.parametrize("pid", list(PORTCOS))
def test_capex_is_cash_not_ebitda(results, pid):
    res = results[pid]
    capex = by_driver(res)["capex_pct"]
    assert capex["ebitda_role"] == CASH
    levers = [d for d in res["drivers"]
              if d["ebitda_role"] in ("lever", "lever_overlap")]
    rebuilt_high = sum(
        (d.get("gap_to_top_quartile_usd", 0) if d.get("confidence") == "high"
         else d.get("gap_to_median_usd", 0))
        for d in levers if d.get("available"))
    assert res["totals"]["ebitda_gap_high_usd"] == pytest.approx(rebuilt_high)
    # CAPEX surfaces only as a cash opportunity.
    assert res["totals"]["cash_opportunity_usd"] == pytest.approx(
        capex.get("gap_to_top_quartile_usd", 0.0))


@pytest.mark.parametrize("pid", list(PORTCOS))
def test_rollup_not_double_counted(results, pid):
    """SG&A contains G&A; adding both would double-count."""
    res = results[pid]
    sga = by_driver(res)["overhead_pct"]
    assert sga["ebitda_role"] == ROLLUP
    assert "gap_to_median_usd" not in sga
    assert "SG&A (total overhead)" in res["totals"]["excluded"]["rollups"]


@pytest.mark.parametrize("pid", list(PORTCOS))
def test_range_is_ordered_and_non_negative(results, pid):
    t = results[pid]["totals"]
    assert 0 <= t["ebitda_gap_low_usd"] <= t["ebitda_gap_high_usd"]
    for d in results[pid]["drivers"]:
        for k in ("gap_to_median_usd", "gap_to_top_quartile_usd"):
            if k in d:
                assert d[k] >= 0


def test_at_median_driver_has_no_median_gap(results):
    # The pharma sample's advertising sits at the median: nothing to close.
    adv = by_driver(results["pharma-sample"])["advertising_pct"]
    assert adv["gap_to_median_usd"] == pytest.approx(0.0, abs=1e5)


def test_stretch_target_not_built_on_medium_confidence_data(results):
    """Below high confidence the stretch case must fall back to the median."""
    d = by_driver(results["pharma-sample"])["ga_pct"]
    assert d["confidence"] != "high"
    t = results["pharma-sample"]["totals"]
    fac = by_driver(results["pharma-sample"])["facilities_pct"]
    assert t["ebitda_gap_high_usd"] == pytest.approx(
        d["gap_to_median_usd"] + fac["gap_to_median_usd"]
        + by_driver(results["pharma-sample"])["advertising_pct"]["gap_to_median_usd"])


def test_totals_are_labelled_as_gaps_not_savings(results):
    for res in results.values():
        assert res["totals"]["nature"] == "benchmark_gap_not_committed_savings"


# --- peer widening ------------------------------------------------------------

def test_peers_never_leave_biotech_and_pharma():
    """Even the widest step stays inside the two industries."""
    for industry in ("biotech", "pharma"):
        steps = list(bm.peer_candidates(industry, ">5B", 2025))
        for frame, relax, level in steps:
            assert set(frame["industry"]) <= {"biotech", "pharma"}
        assert steps[-1][2] == "drugs"


def test_thin_cell_widens_and_says_how():
    """Pharma over $5B holds only a handful of filers per year."""
    p = bm.driver_peers("ga_pct", "pharma", ">5B", 2025)
    assert p["relaxations"], "a thin cell must report its widening"


def test_relaxations_describe_each_step_not_a_running_total():
    steps = {tuple(r) for _, r, _ in bm.peer_candidates("pharma", "250M-1B", 2025)}
    assert ("adjacent_revenue_bands",) in steps, \
        "the adjacent-band step must not also claim all years were pooled"


def test_sub_10m_company_is_compared_with_nearest_band():
    r = bm.compare_driver("ga_pct", {"revenue": 6e6, "ga": 3e6}, "biotech", 2025)
    assert "adjacent_revenue_bands" in r["relaxations"]


# --- confidence ---------------------------------------------------------------

def test_confidence_levels():
    assert bm._confidence(80, "industry") == "high"
    assert bm._confidence(30, "industry") == "medium"
    # Neighbouring size bands cap confidence at medium however many peers.
    assert bm._confidence(200, "industry", ["adjacent_revenue_bands"]) == "medium"
    # Biotech and pharma combined is structurally weak regardless of n.
    assert bm._confidence(500, "drugs") == "low"


def test_every_driver_reports_its_peer_basis(results):
    for res in results.values():
        for d in res["drivers"]:
            assert "n" in d and "relaxations" in d and "industry_level" in d


def test_reference_year_skips_a_partially_filed_year():
    counts = bm.load_panel().groupby("fy")["cik"].nunique()
    ref = bm.reference_year()
    assert counts[ref] >= 0.9 * counts.max()
    assert all(counts[y] < 0.9 * counts.max() for y in counts.index if y > ref)


def test_biotech_and_pharma_cost_structures_differ():
    """The reason they are separate industries at all."""
    b = bm.industry_profile("biotech", "250M-1B")
    p = bm.industry_profile("pharma", "250M-1B")
    rnd = lambda prof: next(d for d in prof["drivers"] if d["driver"] == "rnd_pct")["median"]
    assert rnd(b) > 1.5 * rnd(p)
