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
    assert rev["difference"] == pytest.approx(2.0)          # 34% vs 32%
    assert rev["difference_unit"] == "pp" and rev["favourable"] is False
    gp = m["sga_pct_gross_profit"]
    assert gp["value"] == pytest.approx(163.2 / 264)
    assert gp["difference"] == pytest.approx((163.2 / 264 - 0.53) * 100)


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


def test_benchmarks_are_marked_as_placeholders():
    r = insights.compute(PORTCOS["pharma-sample"], "biotech")
    assert r["benchmarks_are_placeholder"] is True
    assert by_key(r)["sga_pct_revenue"]["benchmark"] == 0.51


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
