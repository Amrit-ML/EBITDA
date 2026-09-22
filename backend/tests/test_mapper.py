"""AI-assisted mapping tests, with a scripted model -- no `claude` CLI call.

This is the fallback for the common case a synonym list cannot cover: real
exports say things like "Topline revenue" or "Cost of sales - products" that
no fixed pattern list will ever fully anticipate. The model only supplies
JUDGMENT (which label means which field); these tests check the code-side
safety net around it, since a wrong mapping here produces a wrong benchmark
silently.
"""

import json

import pytest

from core import llm, mapper

FIELDS = {"revenue": "Revenue", "ga": "G&A", "cost_of_revenue": "Cost of revenue"}


def fake(text):
    def _f(prompt, model=None, timeout=None):
        return llm.LLMResult(text=text, model="fake", duration_s=0.01, cost_usd=0.01)
    return _f


def test_maps_labels_the_synonym_list_cannot(monkeypatch):
    monkeypatch.setattr(llm, "complete", fake(json.dumps({
        "mapping": {"revenue": "Topline", "ga": "Corporate overhead"}})))
    out = mapper.suggest(["Topline", "Corporate overhead", "COGS"], FIELDS)
    assert out == {"revenue": "Topline", "ga": "Corporate overhead"}


def test_cannot_invent_a_label_that_is_not_in_the_file(monkeypatch):
    """The model may hallucinate a plausible-sounding label; code must reject it."""
    monkeypatch.setattr(llm, "complete", fake(json.dumps({
        "mapping": {"revenue": "Total Net Revenues (a label not in the file)"}})))
    out = mapper.suggest(["Topline", "COGS"], FIELDS)
    assert out == {}


def test_cannot_map_a_field_that_was_not_asked_for(monkeypatch):
    monkeypatch.setattr(llm, "complete", fake(json.dumps({
        "mapping": {"revenue": "Topline", "not_a_real_field": "Topline"}})))
    out = mapper.suggest(["Topline"], FIELDS)
    assert out == {"revenue": "Topline"}


def test_label_matching_is_case_insensitive_but_returns_the_real_spelling(monkeypatch):
    monkeypatch.setattr(llm, "complete", fake(json.dumps({
        "mapping": {"revenue": "TOPLINE"}})))
    out = mapper.suggest(["Topline"], FIELDS)
    assert out == {"revenue": "Topline"}


def test_tolerates_code_fences_and_surrounding_prose(monkeypatch):
    monkeypatch.setattr(llm, "complete", fake(
        'Sure, here is the mapping:\n```json\n{"mapping": {"revenue": "Topline"}}\n```'))
    assert mapper.suggest(["Topline"], FIELDS) == {"revenue": "Topline"}


def test_model_failure_degrades_to_empty_not_an_exception(monkeypatch):
    """A missing AI suggestion must leave the user with manual mapping, not a 500."""
    def boom(*a, **kw):
        raise llm.LLMError("CLI exploded")
    monkeypatch.setattr(llm, "complete", boom)
    assert mapper.suggest(["Topline"], FIELDS) == {}


def test_non_json_reply_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(llm, "complete", fake("I don't understand the task"))
    assert mapper.suggest(["Topline"], FIELDS) == {}


def test_no_labels_or_fields_is_a_noop():
    assert mapper.suggest([], FIELDS) == {}
    assert mapper.suggest(["Topline"], {}) == {}
