"""Insights (core/insights.py): the eight ratios, how each is compared with
its benchmark, and headcount entry. No model is called."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
from core import insights
from core.portcos import PORTCOS
from main import app

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


# Fixed Damodaran rows, so tests do not move when the real file is rebuilt.
DAMODARAN_CSV = """industry,source_industry,firms,gross_margin,sga_pct_revenue,as_of
biotech,Drugs (Biotechnology),496,0.60,0.30,January 2026
pharma,Drugs (Pharmaceutical),228,0.72,0.22,January 2026
"""


@pytest.fixture(autouse=True)
def damodaran_file(tmp_path, monkeypatch):
    path = tmp_path / "damodaran_margins.csv"
    path.write_text(DAMODARAN_CSV, encoding="utf-8")
    monkeypatch.setattr(config, "DAMODARAN_PATH", path)
    insights.damodaran.cache_clear()
    yield path
    insights.damodaran.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def by_key(result):
    return {m["key"]: m for m in result["metrics"]}


def test_sga_shares_compare_in_percentage_points():
    # pharma-sample: G&A $96.0M + S&M $67.2M = $163.2M on $480M revenue,
    # cost of revenue $216M, so gross profit $264M.
    m = by_key(insights.compute(PORTCOS["pharma-sample"], "pharma"))
    rev = m["sga_pct_revenue"]
    assert rev["value"] == pytest.approx(0.34)
    assert rev["difference"] == pytest.approx(12.0)         # 34% vs 22%
    assert rev["difference_unit"] == "pp" and rev["favourable"] is False
    gp = m["sga_pct_gross_profit"]
    assert gp["value"] == pytest.approx(163.2 / 264)
    # Peer SG&A / gross profit = (SG&A / sales) / gross margin.
    assert gp["benchmark"] == pytest.approx(0.22 / 0.72)
    assert gp["difference"] == pytest.approx((163.2 / 264 - 0.22 / 0.72) * 100)


def test_per_employee_rows_ask_for_headcount_until_given():
    m = by_key(insights.compute(PORTCOS["pharma-sample"], "pharma"))
    for k in ("sga_per_employee", "revenue_per_employee",
              "gross_profit_per_employee", "ebitda_per_employee", "sga_fte_pct"):
        assert m[k]["value"] is None and m[k]["missing"] == "Add total employees"


def test_dollar_rows_compare_in_percent_and_respect_direction():
    c = {**PORTCOS["pharma-sample"], "headcount": {"total_fte": 1200, "sga_fte": 300}}
    m = by_key(insights.compute(c, "pharma"))
    rpe = m["revenue_per_employee"]                          # $400K vs $550K
    assert rpe["value"] == pytest.approx(400_000)
    assert rpe["difference"] == pytest.approx((400_000 - 550_000) / 550_000 * 100)
    assert rpe["difference_unit"] == "%"
    assert rpe["favourable"] is False                        # higher is better
    fte = m["sga_fte_pct"]                                   # 25% vs 28%
    assert fte["difference"] == pytest.approx(-3.0) and fte["favourable"] is True


def test_sga_ratios_use_damodaran_and_the_rest_are_marked_examples():
    r = insights.compute(PORTCOS["pharma-sample"], "biotech")
    m = by_key(r)
    assert m["sga_pct_revenue"]["benchmark"] == pytest.approx(0.30)
    assert m["sga_pct_revenue"]["benchmark_source"] == "damodaran"
    assert m["sga_pct_gross_profit"]["benchmark_source"] == "damodaran"
    assert m["revenue_per_employee"]["benchmark_source"] == "example"
    assert r["benchmarks_are_placeholder"] is True
    assert "Damodaran" in r["benchmark_source_note"] and "496" in r["benchmark_source_note"]


def test_without_the_damodaran_file_every_benchmark_is_an_example(damodaran_file):
    damodaran_file.unlink()
    insights.damodaran.cache_clear()
    r = insights.compute(PORTCOS["pharma-sample"], "pharma")
    assert {m["benchmark_source"] for m in r["metrics"]} == {"example"}
    assert by_key(r)["sga_pct_revenue"]["benchmark"] == 0.32
    assert r["benchmark_source_note"] is None


def test_growth_gap_needs_two_periods_then_measures_first_to_latest(client):
    sample = SAMPLES / "pharma_pl_quarterly_thousands.csv"
    with sample.open("rb") as fh:
        prev = client.post("/api/uploads", files={"file": (sample.name, fh, "text/csv")}).json()
    mapping = {f: s["label"] for f, s in prev["suggested_mapping"].items()}
    cid = client.post("/api/uploads/company", json={
        "upload_id": prev["upload_id"], "mapping": mapping,
        "period": prev["default_period"], "units": "thousands",
        "industry": "pharma", "fiscal_year": 2024}).json()["company"]["id"]

    r = client.get(f"/api/companies/{cid}/insights").json()
    g = by_key(r)["sga_growth_vs_revenue_growth"]
    assert g["value"] is not None and g["difference_unit"] == "pp"
    assert r["growth_basis"] and " to " in r["growth_basis"]


def test_headcount_is_saved_with_the_company_and_validated(client):
    sample = SAMPLES / "pharma_pl_line_items_thousands.csv"
    with sample.open("rb") as fh:
        prev = client.post("/api/uploads", files={"file": (sample.name, fh, "text/csv")}).json()
    mapping = {f: s["label"] for f, s in prev["suggested_mapping"].items()}
    cid = client.post("/api/uploads/company", json={
        "upload_id": prev["upload_id"], "mapping": mapping,
        "period": prev["default_period"], "units": "thousands",
        "industry": "pharma", "fiscal_year": 2024}).json()["company"]["id"]

    bad = client.put(f"/api/companies/{cid}/headcount", json={"total_fte": 100, "sga_fte": 150})
    assert bad.status_code == 422

    r = client.put(f"/api/companies/{cid}/headcount", json={"total_fte": 800, "sga_fte": 200})
    assert r.status_code == 200
    assert by_key(r.json())["sga_fte_pct"]["value"] == pytest.approx(0.25)
    saved = json.loads((config.HISTORY_DIR / "companies" / f"{cid}.json").read_text())
    assert saved["company"]["headcount"] == {"total_fte": 800, "sga_fte": 200}


def test_missing_values_say_what_would_fill_them():
    m = by_key(insights.compute(PORTCOS["pharma-sample"], "pharma"))
    assert m["revenue_per_employee"]["action"] == "add_total_fte"
    assert m["sga_pct_revenue"]["action"] is None               # has a value
    c = {**PORTCOS["pharma-sample"], "headcount": {"total_fte": 900, "sga_fte": None}}
    assert by_key(insights.compute(c, "pharma"))["sga_fte_pct"]["action"] == "add_sga_fte"
    old_trend = {"periods": ["Q1 2025", "Q2 2025"], "revenue": [1, 2], "ebitda": [1, 1]}
    g = by_key(insights.compute({**c, "trend": old_trend}, "pharma"))["sga_growth_vs_revenue_growth"]
    assert g["action"] == "reupload"


def test_replacing_a_pl_keeps_its_headcount(client):
    def upload(carry=None):
        sample = SAMPLES / "pharma_pl_line_items_thousands.csv"
        with sample.open("rb") as fh:
            prev = client.post("/api/uploads", files={"file": (sample.name, fh, "text/csv")}).json()
        mapping = {f: s["label"] for f, s in prev["suggested_mapping"].items()}
        return client.post("/api/uploads/company", json={
            "upload_id": prev["upload_id"], "mapping": mapping, "carry_context_from": carry,
            "period": prev["default_period"], "units": "thousands",
            "industry": "pharma", "fiscal_year": 2024}).json()["company"]["id"]

    first = upload()
    client.put(f"/api/companies/{first}/headcount", json={"total_fte": 640, "sga_fte": 150})
    second = upload(carry=first)
    r = client.get(f"/api/companies/{second}/insights").json()
    assert r["headcount"] == {"total_fte": 640, "sga_fte": 150}
    assert client.get(f"/api/companies/{upload()}/insights").json()["headcount"]["total_fte"] is None


def _with_trend(sga, revenue):
    return {**PORTCOS["pharma-sample"], "trend": {
        "periods": ["Q1 2025", "Q4 2025"], "revenue": revenue, "sga": sga, "ebitda": [1, 1]}}


def test_growth_gap_reports_the_two_rates_behind_it():
    g = by_key(insights.compute(_with_trend([100, 120], [200, 220]), "pharma"))[
        "sga_growth_vs_revenue_growth"]
    assert g["value"] == pytest.approx(10.0)
    assert g["parts"] == {"sga_growth": pytest.approx(0.2), "revenue_growth": pytest.approx(0.1)}
    assert by_key(insights.compute(PORTCOS["pharma-sample"], "pharma"))[
        "sga_pct_revenue"]["parts"] is None


def test_a_gap_that_rounds_to_zero_is_level_not_worse():
    # SG&A +10.03%, revenue +10% -> +0.03 pp, shown as "+0.0 pp".
    g = by_key(insights.compute(_with_trend([100_000, 110_030], [100_000, 110_000]), "pharma"))[
        "sga_growth_vs_revenue_growth"]
    assert g["difference"] == pytest.approx(0.03)
    assert g["favourable"] is None


def test_improvements_cover_every_unfavourable_ratio_largest_gap_first():
    c = {**PORTCOS["pharma-sample"], "headcount": {"total_fte": 1300, "sga_fte": 400}}
    r = insights.compute(c, "pharma")
    unfavourable = {m["key"] for m in r["metrics"] if m["favourable"] is False}
    imp = r["improvements"]
    assert {i["key"] for i in imp} == unfavourable
    assert all(i["area"] and i["why"] and i["first_step"] for i in imp)
    # SG&A % revenue: 34% vs 22% is a far larger gap than SG&A FTE 30.8% vs 28%.
    keys = [i["key"] for i in imp]
    assert keys.index("sga_pct_revenue") < keys.index("sga_fte_pct")


def test_every_ratio_has_improvement_wording():
    assert {k for k, *_ in insights.METRICS} == set(insights.IMPROVEMENTS)
