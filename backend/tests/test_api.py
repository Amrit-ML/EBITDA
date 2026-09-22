"""API and agent-loop tests with a scripted fake model.

No `claude` CLI call is made: llm.complete is replaced with a queue of canned
replies. That exercises the real loop -- recording opportunities, the dollar
guard and its retry, error rollback -- deterministically and for free.
"""

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import llm
from main import app

PHARMA = "pharma-sample"      # $480M specialty pharma, G&A $96.0M
BIOTECH = "biotech-sample"    # $520M commercial-stage biotech
SAMPLES = Path(__file__).resolve().parents[2] / "samples"


class FakeLLM:
    def __init__(self):
        self.replies = []
        self.prompts = []

    def queue(self, *objs):
        for o in objs:
            self.replies.append(o if isinstance(o, (str, Exception))
                                else json.dumps(o))

    def __call__(self, prompt, model=None, timeout=None):
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("fake model called more times than scripted")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return llm.LLMResult(text=r, model="fake", duration_s=0.01,
                             cost_usd=0.05)


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete", f)
    monkeypatch.setattr(llm, "find_claude_bin", lambda: "fake-claude")
    return f


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def msg(text, **kw):
    return {"facts": {}, "findings": [], "message": text,
            "stage": "interviewing", **kw}


def upload_csv(client, content: bytes, name="pl.csv"):
    return client.post("/api/uploads",
                       files={"file": (name, io.BytesIO(content), "text/csv")}).json()


# --- read-only endpoints ------------------------------------------------------

def test_health(client, fake):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["filers"] >= 250


def test_samples_listed_and_marked_synthetic(client):
    rows = [r for r in client.get("/api/companies").json()["results"]
            if not r["uploaded"]]
    assert {r["id"] for r in rows} == {PHARMA, BIOTECH}
    assert all(r["synthetic"] for r in rows)
    assert {r["industry"] for r in rows} == {"pharma", "biotech"}


def test_sample_detail_does_not_leak_hidden_facts(client):
    d = client.get(f"/api/companies/{PHARMA}").json()
    assert "hidden_facts" not in d and "planted" not in d


def test_briefing_exposes_hidden_facts_for_operator(client):
    b = client.get(f"/api/companies/{PHARMA}/briefing").json()
    assert b["hidden_facts"]["ga_headcount"] == 260


def test_benchmark_is_deterministic_and_needs_no_model(client, fake):
    r = client.get(f"/api/companies/{PHARMA}/benchmark").json()
    assert fake.prompts == [], "benchmark endpoint must not call the model"
    assert r["totals"]["nature"] == "benchmark_gap_not_committed_savings"


def test_unknown_company_404(client):
    assert client.get("/api/companies/nope").status_code == 404
    assert client.post("/api/sessions", json={"company_id": "nope"}).status_code == 404


# --- agent loop ---------------------------------------------------------------

def test_opening_turn(client, fake):
    fake.queue(msg("Your G&A is at the 79th percentile. How many finance teams?"))
    r = client.post("/api/sessions", json={"company_id": PHARMA}).json()
    assert r["session_id"] and "G&A" in r["message"]
    assert r["comparison"]["company"]["revenue"] == 480_000_000
    assert len(fake.prompts) == 1
    # The model is given no savings or dollar gaps, and never sees hidden facts.
    assert "NO SAVINGS OR DOLLAR GAPS ARE COMPUTED" in fake.prompts[0]
    assert "gap to median" not in fake.prompts[0]
    assert "New Jersey" not in fake.prompts[0]


def test_opportunity_turn_is_one_call_with_no_saving(client, fake):
    fake.queue(msg("How many finance teams?"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]

    fake.queue(
        msg("Three separate back offices is the gap. Start with finance. "
            "Which one closes the books slowest?",
            facts={"acquisitions": "3, each with its own back office"},
            findings=[{"driver": "ga_pct", "lever": "Integrate acquired back offices",
                       "rationale": "three duplicated back offices",
                       "first_step": "Move the smallest onto the parent's close",
                       "based_on": ["acquisitions"]}]),
    )
    r = client.post(f"/api/sessions/{sid}/messages",
                    json={"text": "Three acquisitions kept their own back office"}).json()

    assert [t["step"] for t in r["trace"]] == ["respond"]
    f = r["findings"][0]
    assert f["lever"] == "Integrate acquired back offices"
    assert f["first_step"].startswith("Move the smallest")
    assert not any("saving" in k for k in f)
    assert r["findings_totals"] == {"count": 1}
    assert r["facts"]["acquisitions"].startswith("3")
    assert r["guard"]["unverified_figures"] == []


def test_guard_retries_then_flags_invented_figures(client, fake):
    fake.queue(msg("Opening"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]

    fake.queue(msg("You could easily save $190M."),
               msg("Honestly, $190M is achievable."))
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "how much?"}).json()

    assert [t["step"] for t in r["trace"]] == ["respond", "guard_retry"]
    assert r["guard"]["unverified_figures"] == ["$190.0M"]


def test_guard_retry_can_fix_the_reply(client, fake):
    fake.queue(msg("Opening"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]
    fake.queue(msg("Save $190M."), msg("Your G&A runs about $96M a year."))
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "how much?"}).json()
    assert r["guard"]["unverified_figures"] == []
    assert "$96M" in r["message"]


def test_guard_catches_a_peer_dollar_gap(client, fake):
    """A dollar distance to peers reads as a saving, so it is sent back."""
    fake.queue(msg("Opening"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]
    bench = client.get(f"/api/companies/{PHARMA}/benchmark").json()
    # Facilities: its gap sits near no spend figure, so rounding cannot hide it.
    fac = next(d for d in bench["drivers"] if d["driver"] == "facilities_pct")
    gap = f"${fac['gap_to_median_usd'] / 1e6:.1f}M"
    fake.queue(msg(f"Space costs {gap} more than at similar companies."),
               msg("You spend more on space than most companies your size."))
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "how far off?"}).json()
    assert [t["step"] for t in r["trace"]] == ["respond", "guard_retry"]
    assert gap not in r["message"] and r["guard"]["unverified_figures"] == []


def test_model_cannot_target_rnd(client, fake):
    fake.queue(msg("Opening"))
    sid = client.post("/api/sessions", json={"company_id": BIOTECH}).json()["session_id"]
    fake.queue(msg("I'd cut R&D.", findings=[{
        "driver": "rnd_pct", "lever": "Halve R&D", "based_on": ["x"]}]))
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "cut R&D?"}).json()
    assert r["findings"] == []
    assert [t["step"] for t in r["trace"]] == ["respond"]


def test_model_failure_returns_502_and_rolls_back(client, fake):
    fake.queue(msg("Opening"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]
    fake.queue(llm.LLMError("CLI exploded"))
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "hello"})
    assert r.status_code == 502
    state = client.get(f"/api/sessions/{sid}").json()
    assert [h["role"] for h in state["history"]] == ["assistant"], \
        "the failed user message must not linger in history"


def test_unparseable_model_reply_is_a_502(client, fake):
    fake.queue(msg("Opening"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]
    fake.queue("I refuse to answer in JSON")
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    assert r.status_code == 502


def test_unknown_session_404(client):
    r = client.post("/api/sessions/deadbeef/messages", json={"text": "hi"})
    assert r.status_code == 404


def test_session_state_tracks_cost(client, fake):
    fake.queue(msg("Opening"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]
    s = client.get(f"/api/sessions/{sid}").json()
    assert s["model_calls"] == 1 and s["total_cost_usd"] == pytest.approx(0.05)


def test_empty_message_rejected(client, fake):
    fake.queue(msg("Opening"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]
    assert client.post(f"/api/sessions/{sid}/messages",
                       json={"text": ""}).status_code == 422


# --- upload flow ----------------------------------------------------------------

def test_upload_to_diagnostic_end_to_end(client, fake):
    sample = SAMPLES / "pharma_pl_line_items_thousands.csv"
    with sample.open("rb") as fh:
        prev = client.post("/api/uploads",
                           files={"file": (sample.name, fh, "text/csv")}).json()
    assert prev["orientation"] == "rows"
    assert prev["detected_units"] == "thousands"

    mapping = {f: s["label"] for f, s in prev["suggested_mapping"].items()}
    made = client.post("/api/uploads/company", json={
        "upload_id": prev["upload_id"], "mapping": mapping,
        "period": prev["default_period"], "units": "thousands",
        "industry": "pharma", "fiscal_year": 2024}).json()
    cid = made["company"]["id"]
    assert made["financials"]["revenue"] == pytest.approx(310_000_000)
    assert made["company"]["uploaded"] is True

    listed = {r["id"] for r in client.get("/api/companies").json()["results"]}
    assert cid in listed

    bench = client.get(f"/api/companies/{cid}/benchmark").json()
    assert bench["company"]["revenue_band"] == "250M-1B"
    assert bench["company"]["industry"] == "pharma"
    assert client.get(f"/api/companies/{cid}/briefing").json()["hidden_facts"] == {}

    fake.queue(msg("Your G&A is high. How many finance teams?"))
    r = client.post("/api/sessions", json={"company_id": cid}).json()
    assert r["session_id"]
    # An uploaded company must not be described to the model as synthetic.
    assert "a P&L uploaded by the user" in fake.prompts[-1]
    assert "SYNTHETIC" not in fake.prompts[-1]


def test_upload_without_revenue_is_rejected(client):
    prev = upload_csv(client, b"Line,FY2024\nG&A,100\nRent,20\n", "x.csv")
    assert prev["warning"]
    mapping = {f: s["label"] for f, s in prev["suggested_mapping"].items()}
    r = client.post("/api/uploads/company", json={
        "upload_id": prev["upload_id"], "mapping": mapping,
        "period": prev["default_period"], "industry": "pharma",
        "fiscal_year": 2024})
    assert r.status_code == 400 and "Revenue" in r.json()["detail"]


def test_upload_needs_no_company_name(client):
    prev = upload_csv(client, b"Line,FY2024\nRevenue,1000\nG&A,100\n")
    mapping = {f: s["label"] for f, s in prev["suggested_mapping"].items()}
    r = client.post("/api/uploads/company", json={
        "upload_id": prev["upload_id"], "mapping": mapping,
        "period": prev["default_period"], "units": "millions",
        "industry": "biotech", "fiscal_year": 2024})
    assert r.status_code == 200, r.text
    c = r.json()["company"]
    assert c["name"] == "Your company" and c["industry"] == "biotech"
    assert c["revenue"] == pytest.approx(1e9)


def test_ai_mapping_fills_labels_the_synonym_list_misses(client, fake):
    """This is the "just upload it" case: no recognisable synonyms at all,
    but the model can still read what a human would.

    Labels are chosen to avoid the fixed synonym list entirely (it already
    matches bare words like "sales" or "revenue" anywhere), so this is a real
    exercise of the AI fallback, not an accidental synonym hit.
    """
    lines = [
        "Item,FY2024",
        "Topline,480000000",
        "Direct cost outlay,216000000",
        "Corporate overhead,96000000",
    ]
    csv = ("\n".join(lines) + "\n").encode("utf-8")
    fake.queue({"mapping": {
        "revenue": "Topline",
        "cost_of_revenue": "Direct cost outlay",
        "ga": "Corporate overhead",
    }})
    prev = upload_csv(client, csv, "bespoke.csv")
    assert sorted(prev["ai_mapped"]) == sorted(["revenue", "cost_of_revenue", "ga"])
    assert prev["suggested_mapping"]["revenue"] == {
        "label": "Topline", "confidence": "ai"}

    # The user can benchmark it without touching the mapping table.
    mapping = {f: s["label"] for f, s in prev["suggested_mapping"].items()}
    made = client.post("/api/uploads/company", json={
        "upload_id": prev["upload_id"], "mapping": mapping,
        "period": prev["default_period"], "units": "dollars",
        "industry": "pharma", "fiscal_year": 2024}).json()
    assert made["financials"]["revenue"] == pytest.approx(480_000_000)
    assert made["financials"]["ga"] == pytest.approx(96_000_000)


def test_ai_mapper_is_not_called_when_the_synonym_list_already_did_enough(client, fake):
    """A well-labelled file must never spend a model call."""
    lines = [
        "Line,FY2024", "Revenue,1000", "Cost of revenue,400",
        "G&A,100", "R&D,50", "Operating income,200",
    ]
    upload_csv(client, ("\n".join(lines) + "\n").encode("utf-8"))
    assert fake.prompts == []


@pytest.mark.parametrize("industry", ["software", "35", ""])
def test_upload_into_other_industry_rejected(client, industry):
    prev = upload_csv(client, b"Line,FY2024\nRevenue,1000\n")
    r = client.post("/api/uploads/company", json={
        "upload_id": prev["upload_id"], "mapping": {"revenue": "Revenue"},
        "period": prev["default_period"], "industry": industry,
        "fiscal_year": 2024})
    assert r.status_code == 422


# --- two industries ---------------------------------------------------------------
# Users choose Biotechnology or Pharmaceutical and bring a P&L. They never pick
# or name a company.

def test_only_biotech_and_pharma_are_offered(client):
    rows = client.get("/api/industries").json()["results"]
    assert [r["id"] for r in rows] == ["biotech", "pharma"]
    assert [r["label"] for r in rows] == ["Biotechnology", "Pharmaceutical"]
    assert all(r["filers"] >= 50 for r in rows)


@pytest.mark.parametrize("path", [
    "/api/industries/software/profile",
    "/api/industries/35/profile",
    f"/api/companies/{PHARMA}/benchmark?industry=software",
])
def test_other_industries_are_rejected(client, path):
    assert client.get(path).status_code == 422


def test_industry_profile_needs_no_company_or_model(client, fake):
    p = client.get("/api/industries/pharma/profile").json()
    assert fake.prompts == []
    assert p["id"] == "pharma" and p["band"] is None and p["filers"] >= 50
    assert p["years"] == [p["fiscal_year"] - 2, p["fiscal_year"] - 1, p["fiscal_year"]]
    by = {d["driver"]: d for d in p["drivers"]}
    ga = by["ga_pct"]
    assert ga["available"] and ga["p10"] <= ga["p25"] <= ga["median"] <= ga["p75"] <= ga["p90"]
    assert [b["band"] for b in p["bands"]] == client.get("/api/meta").json()["revenue_bands"]


def test_pre_commercial_band_is_not_offered(client):
    """Peers need $10M+ revenue, so the sub-$10M band has no peers to show."""
    p = client.get("/api/industries/biotech/profile").json()
    assert "<10M" not in [b["band"] for b in p["bands"]]
    assert client.get("/api/industries/biotech/profile",
                      params={"band": "<10M"}).status_code == 400


def test_industry_profile_by_size_band(client):
    all_sizes = client.get("/api/industries/biotech/profile").json()
    mid = client.get("/api/industries/biotech/profile", params={"band": "250M-1B"}).json()
    assert mid["band"] == "250M-1B" and mid["filers"] < all_sizes["filers"]


@pytest.mark.parametrize("cid,industry", [(PHARMA, "pharma"), (BIOTECH, "biotech")])
def test_industry_profile_matches_what_a_pl_is_ranked_against(client, cid, industry):
    """The medians shown before upload must be the ones used after it."""
    prof = client.get(f"/api/industries/{industry}/profile", params={"band": "250M-1B"}).json()
    bench = client.get(f"/api/companies/{cid}/benchmark", params={"industry": industry}).json()
    assert bench["company"]["revenue_band"] == "250M-1B"
    assert bench["company"]["fiscal_year"] == prof["fiscal_year"]
    for d in bench["drivers"]:
        p = next(x for x in prof["drivers"] if x["driver"] == d["driver"])
        if d.get("median") is not None:
            assert d["median"] == pytest.approx(p["median"])
            assert d["n"] == p["n"]


def test_bad_band_rejected(client):
    r = client.get("/api/industries/pharma/profile", params={"band": "huge"})
    assert r.status_code == 400


def test_benchmark_follows_the_selected_industry(client):
    own = client.get(f"/api/companies/{BIOTECH}/benchmark").json()
    other = client.get(f"/api/companies/{BIOTECH}/benchmark", params={"industry": "pharma"}).json()
    assert own["company"]["industry"] == "biotech"
    assert other["company"]["industry"] == "pharma"
    rnd = lambda c: next(d for d in c["drivers"] if d["driver"] == "rnd_pct")["median"]
    assert rnd(own) > rnd(other), "biotech R&D intensity should exceed pharma's"


def test_session_uses_selected_industry_and_no_company_name(client, fake):
    fake.queue(msg("Your G&A is high. How many finance teams?"))
    r = client.post("/api/sessions", json={"company_id": PHARMA, "industry": "pharma"}).json()
    prompt = fake.prompts[-1]
    assert r["comparison"]["company"]["industry"] == "pharma"
    assert "Industry: Pharmaceutical" in prompt
    assert "US public pharmaceutical SEC filers" in prompt
    assert "Sample specialty pharma" not in prompt, "sample names must never reach the model"
    assert "your company" in prompt


def test_industry_list_count_matches_profile(client):
    """The count shown in the picker must match the view it opens."""
    rows = {r["id"]: r for r in client.get("/api/industries").json()["results"]}
    for industry in ("biotech", "pharma"):
        prof = client.get(f"/api/industries/{industry}/profile").json()
        assert rows[industry]["filers"] == prof["filers"], industry

def test_upload_rejects_an_image_with_guidance(client):
    r = client.post("/api/uploads",
                    files={"file": ("statement.png", io.BytesIO(b"\x89PNG"),
                                    "image/png")})
    assert r.status_code == 400
    assert "CSV or Excel" in r.json()["detail"]


def test_pdf_statement_uploads_end_to_end(client):
    pdf = Path(__file__).resolve().parent / "fixtures" / "pl_statement.pdf"
    with pdf.open("rb") as fh:
        prev = client.post("/api/uploads",
                           files={"file": (pdf.name, fh, "application/pdf")}).json()
    assert prev["source_kind"] == "pdf" and prev["extraction_note"]
    made = client.post("/api/uploads/company", json={
        "upload_id": prev["upload_id"],
        "mapping": {f: s["label"] for f, s in prev["suggested_mapping"].items()},
        "period": prev["default_period"], "units": prev["detected_units"],
        "industry": "pharma", "fiscal_year": 2025}).json()
    assert made["financials"]["revenue"] == pytest.approx(340_000_000)
    bench = client.get(f"/api/companies/{made['company']['id']}/benchmark").json()
    assert bench["company"]["revenue_band"] == "250M-1B"


def test_upload_size_limit_reports_the_actual_size(client):
    big = io.BytesIO(b"a,b\n" + b"1,2\n" * 6_000_000)
    r = client.post("/api/uploads", files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 413
    assert "MB" in r.json()["detail"]


