"""Agent tests that need no LLM call.

These cover the parts that keep the demo honest: JSON parsing, the dollar-figure
guard, and the code-side checks on recorded opportunities - which never carry
a saving.
"""

import json

import pytest

from core import agent as ag
from core import benchmarks as bm
from core import llm
from core.portcos import PORTCOS


@pytest.fixture
def session():
    p = PORTCOS["pharma-sample"]
    comp = bm.compare_company(p["financials"], p["industry"], p["fiscal_year"])
    return ag.Session(id="t", portco=p, comparison=comp)


# --- parsing -----------------------------------------------------------------

def test_parse_plain_json():
    a = ag.parse_action('{"message": "hi", "stage": "interviewing"}')
    assert a["message"] == "hi" and a["facts"] == {} and a["findings"] == []


def test_parse_strips_code_fences():
    a = ag.parse_action('```json\n{"message": "hi"}\n```')
    assert a["message"] == "hi"


def test_parse_tolerates_surrounding_prose():
    a = ag.parse_action('Sure, here you go: {"message": "hi"} hope that helps')
    assert a["message"] == "hi"


def test_parse_coerces_bad_field_types():
    a = ag.parse_action('{"message": "hi", "facts": "oops", "findings": {}}')
    assert a["facts"] == {} and a["findings"] == []


def test_parse_rejects_non_json():
    with pytest.raises(ValueError):
        ag.parse_action("no json here at all")


# --- dollar guard ------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("$24.5M", [24.5e6]),
    ("$24.5 million", [24.5e6]),
    ("$1.2B", [1.2e9]),
    ("$450k", [450e3]),
    ("$65,100,000", [65.1e6]),
])
def test_extract_money(text, expected):
    assert ag.extract_money(text) == pytest.approx(expected)


def test_guard_accepts_rounded_computed_figures():
    allowed = [24_512_300.0]
    assert ag.unverified_figures("a gap of $24.5M", allowed) == []
    assert ag.unverified_figures("roughly $25M", allowed) == []


def test_guard_flags_invented_figures():
    assert ag.unverified_figures("you could save $90M", [24.5e6]) == ["$90.0M"]


def test_guard_allows_numbers_the_user_volunteered(session):
    session.facts["erp_cost"] = "$3.4M a year"
    assert ag.unverified_figures("your $3.4M ERP spend",
                                 session.allowed_numbers()) == []


def test_company_spend_is_citable(session):
    allowed = session.allowed_numbers()
    assert ag.unverified_figures("G&A runs about $96M a year", allowed) == []


def test_peer_dollar_gap_is_not_citable(session):
    """A dollar distance to peers reads as a saving, so the guard flags it.

    The guard matches within rounding, so a gap that happens to sit near a
    spend figure (G&A's $27.7M is close to $26.4M of advertising) would pass.
    The first defence is that the model is never shown the gaps at all.
    """
    allowed = session.allowed_numbers()
    fac = next(d for d in session.comparison["drivers"]
               if d["driver"] == "facilities_pct")
    gap = f"${fac['gap_to_median_usd'] / 1e6:.1f}M"
    assert ag.unverified_figures(f"Space is {gap} above peers", allowed) == [gap]


# --- opportunities -------------------------------------------------------------

def _opp(driver="ga_pct", lever="Consolidate regional finance", **kw):
    return {"driver": driver, "lever": lever, "rationale": "3 regional HQs",
            "first_step": "Move the smallest site first",
            "based_on": ["regional_hqs"], **kw}


def test_opportunity_carries_the_action_and_todays_rank(session):
    o = session.record_opportunity(_opp())
    ga = next(d for d in session.comparison["drivers"] if d["driver"] == "ga_pct")
    assert o["lever"] == "Consolidate regional finance"
    assert o["first_step"] == "Move the smallest site first"
    assert o["percentile_now"] == ga["percentile"]
    assert o["unsupported"] is False


def test_opportunity_never_carries_a_saving(session):
    """Even if the model sends the old sizing fields, none survive."""
    o = session.record_opportunity(_opp(addressable_low=0.2,
                                        addressable_high=0.4))
    assert not any("saving" in k or "addressable" in k for k in o)
    session.findings.append(o)
    assert "$" not in session.render_findings()


@pytest.mark.parametrize("driver", ["rnd_pct", "ebitda_margin", "overhead_pct",
                                    "not_a_driver"])
def test_protected_or_invalid_drivers_cannot_be_recorded(session, driver):
    """R&D is protected, EBITDA is the outcome, SG&A would repeat G&A."""
    assert session.record_opportunity(_opp(driver=driver)) is None


def test_opportunity_without_an_action_is_dropped(session):
    assert session.record_opportunity(_opp(lever="  ")) is None


def test_opportunity_without_a_cited_fact_is_flagged(session):
    o = session.record_opportunity(_opp(based_on=[]))
    assert o["unsupported"] is True
    assert session.record_opportunity(_opp(based_on="not a list"))["unsupported"]


def test_totals_are_a_count(session):
    session._absorb({"facts": {}, "findings": [_opp(), _opp("facilities_pct",
                                                            "Sub-let Dublin")]})
    assert session.findings_totals() == {"count": 2}


def test_rerecording_an_action_replaces_it(session):
    session._absorb({"facts": {}, "findings": [_opp(rationale="first")]})
    session._absorb({"facts": {}, "findings": [_opp(rationale="second")]})
    assert [o["rationale"] for o in session.findings] == ["second"]


# --- context -----------------------------------------------------------------

def test_context_carries_no_dollar_gaps_or_savings(session):
    ctx = ag.render_context(session.portco, session.comparison)
    assert "NO SAVINGS OR DOLLAR GAPS ARE COMPUTED" in ctx
    assert "gap to median" not in ctx and "TOTAL BENCHMARK GAP" not in ctx
    assert "SYNTHETIC" in ctx
    assert "NOT BENCHMARKABLE" in ctx
    assert "GROWTH - protect" in ctx
    assert "Sample specialty pharma" not in ctx


def test_context_names_the_industry_and_peer_basis(session):
    ctx = ag.render_context(session.portco, session.comparison)
    assert "Industry: Pharmaceutical" in ctx
    assert "at least $10M revenue" in ctx
    assert "FY2023-2025" in ctx


def test_prompt_protects_pipeline_and_compliance_functions():
    assert "pipeline" in ag.SYSTEM
    assert "pharmacovigilance" in ag.SYSTEM


def test_prompt_forbids_estimating_savings():
    assert "You do NOT estimate savings" in ag.SYSTEM
    assert "addressable_low" not in ag.SYSTEM


def test_prompt_builds_with_opportunities_on_one_cost_line(session):
    """Two actions on one cost line once crashed the prompt build (a
    NameError on every turn after the second); it must still build."""
    session._absorb({"facts": {}, "findings": [
        _opp(lever="Consolidate finance teams"),
        _opp(lever="Renegotiate the audit contract")]})
    prompt = session.build_prompt()
    assert "OPPORTUNITIES recorded so far" in prompt
    assert "Renegotiate the audit contract" in prompt


def test_old_saved_findings_with_savings_still_render(session):
    """Sessions saved before savings were dropped still reopen."""
    session.findings.append({
        "id": "old", "driver": "ga_pct", "label": "G&A", "ebitda_role": "lever",
        "lever": "Integrate back offices", "rationale": "three HQs",
        "based_on": ["k"], "savings_low_usd": 9.6e6, "savings_high_usd": 17.3e6})
    assert "Integrate back offices" in session.build_prompt()


# --- streaming -------------------------------------------------------------------

def test_stream_turn_is_one_call_and_streams_as_written(session, monkeypatch):
    """With nothing computed after the model writes, the reply streams straight
    through: one call, no reset, no rewrite step."""
    header = {"facts": {"finance_teams": "four"},
              "findings": [_opp(lever="Consolidate four finance teams")],
              "stage": "recommending"}
    prose = "Four finance teams is the gap.\n\nWhich site closes slowest?"
    reply = json.dumps(header) + "\n\n" + prose
    prompts = []

    def fake_stream(prompt, model=None, timeout=None):
        prompts.append(prompt)
        for i in range(0, len(reply), 9):
            yield reply[i:i + 9]
        yield llm.StreamUsage(model="fake", duration_s=0.01, cost_usd=0.05)

    monkeypatch.setattr(llm, "stream", fake_stream)
    monkeypatch.setattr(ag.Session, "retrieved_context", lambda self: None)
    events = list(session.turn_stream("We run four finance teams"))

    kinds = [e["type"] for e in events]
    assert "reset" not in kinds and len(prompts) == 1
    assert "".join(e["text"] for e in events if e["type"] == "delta") == prose
    done = events[-1]["payload"]
    assert [t["step"] for t in done["trace"]] == ["respond"]
    assert done["findings"][0]["lever"] == "Consolidate four finance teams"
    assert done["findings_totals"] == {"count": 1}


def test_discard_last_user_rolls_back_only_a_trailing_user_turn(session):
    session.history.append({"role": "user", "content": "q"})
    session.discard_last_user()
    assert session.history == []
    session.history.append({"role": "assistant", "content": "a"})
    session.discard_last_user()
    assert session.history == [{"role": "assistant", "content": "a"}]


# --- JSON-first reply shape ------------------------------------------------------

def test_parse_json_first_then_prose():
    a = ag.parse_action('{"facts": {"sites": "five"}, "findings": [], "stage": "interviewing"}\n\nYou run five sites.')
    assert a["facts"] == {"sites": "five"} and a["message"] == "You run five sites."


def test_parse_fence_around_json_only_does_not_leak_into_prose():
    a = ag.parse_action('```json\n{"facts": {}, "findings": [], "stage": "x"}\n```\n\nGood, nothing there.')
    assert a["message"] == "Good, nothing there."
    assert "`" not in a["message"]


def test_parse_brace_inside_string_does_not_end_header():
    a = ag.parse_action('{"facts": {"n": "a } brace"}, "findings": [], "stage": "x"}\n\nProse with { a brace }.')
    assert a["facts"]["n"] == "a } brace" and a["message"] == "Prose with { a brace }."
