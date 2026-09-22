"""Saved diagnostics (core/history.py): saved per turn, reopened after a
restart, continued, and deleted. The model is scripted; nothing is live.

conftest.isolated_history points config.HISTORY_DIR at a temp folder, so these
tests never touch the real chat_history/.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
from core import agent, companies, llm
from main import app

PHARMA = "pharma-sample"
SAMPLES = Path(__file__).resolve().parents[2] / "samples"


class FakeLLM:
    def __init__(self):
        self.replies = []

    def queue(self, *objs):
        self.replies += [o if isinstance(o, Exception) else json.dumps(o) for o in objs]

    def __call__(self, prompt, model=None, timeout=None):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return llm.LLMResult(text=r, model="fake", duration_s=0.01, cost_usd=0.05)


def msg(text):
    return {"facts": {}, "findings": [], "message": text, "stage": "interviewing"}


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete", f)
    return f


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def restart():
    """What a server restart does to memory: every live session is gone."""
    agent._SESSIONS.clear()


def start_and_reply(client, fake):
    fake.queue(msg("Your G&A is high. How many finance teams?"),
               msg("Four teams is a lot. Which sites?"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "Four teams"})
    return sid


def test_each_turn_is_saved_as_a_file_and_listed(client, fake):
    sid = start_and_reply(client, fake)

    assert (config.HISTORY_DIR / "sessions" / f"{sid}.json").exists()
    rows = client.get("/api/sessions").json()["results"]
    assert [r["id"] for r in rows] == [sid]
    row = rows[0]
    assert row["message_count"] == 3          # opening, user, reply
    assert row["industry"] == "pharma" and row["revenue"] == 480_000_000
    assert row["preview"].startswith("Four teams is a lot")


def test_saved_diagnostic_reopens_after_restart_and_continues(client, fake):
    sid = start_and_reply(client, fake)
    restart()

    r = client.get(f"/api/sessions/{sid}").json()
    assert [m["role"] for m in r["messages"]] == ["assistant", "user", "assistant"]
    assert r["messages"][1]["content"] == "Four teams"
    assert r["messages"][2]["guard"]["checked"] is True
    assert r["company"]["id"] == PHARMA and r["industry"] == "pharma"

    # The reopened session is live again: the conversation carries on.
    fake.queue(msg("Understood. Next question?"))
    turn = client.post(f"/api/sessions/{sid}/messages", json={"text": "Raleigh"})
    assert turn.status_code == 200
    rows = client.get("/api/sessions").json()["results"]
    assert rows[0]["message_count"] == 5


def test_a_failed_turn_is_not_saved(client, fake):
    fake.queue(msg("Opening. How many finance teams?"), llm.LLMError("boom"))
    sid = client.post("/api/sessions", json={"company_id": PHARMA}).json()["session_id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "Four"})
    assert r.status_code == 502

    restart()
    saved = client.get(f"/api/sessions/{sid}").json()
    assert len(saved["messages"]) == 1
    assert all(h["content"] != "Four" for h in saved["history"])


def test_uploaded_pl_survives_a_restart(fake):
    sample = SAMPLES / "pharma_pl_quarterly_thousands.csv"
    with TestClient(app) as client:
        with sample.open("rb") as fh:
            prev = client.post("/api/uploads",
                               files={"file": (sample.name, fh, "text/csv")}).json()
        mapping = {f: s["label"] for f, s in prev["suggested_mapping"].items()}
        made = client.post("/api/uploads/company", json={
            "upload_id": prev["upload_id"], "mapping": mapping,
            "period": prev["default_period"], "units": "thousands",
            "industry": "pharma", "fiscal_year": 2024}).json()
        cid = made["company"]["id"]
        assert made["trend"] and len(made["trend"]["periods"]) >= 2

    companies._UPLOADED.pop(cid)
    with TestClient(app) as client:          # startup reloads saved P&Ls
        r = client.get(f"/api/companies/{cid}")
        assert r.status_code == 200
        assert companies.get(cid)["trend"]["periods"] == made["trend"]["periods"]


def test_delete_removes_the_diagnostic(client, fake):
    sid = start_and_reply(client, fake)
    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    assert client.get("/api/sessions").json()["results"] == []
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.delete(f"/api/sessions/{sid}").status_code == 404


@pytest.mark.parametrize("bad", ["..", "a.b", "x" * 65])
def test_ids_that_could_leave_the_history_folder_are_refused(client, bad):
    assert client.get(f"/api/sessions/{bad}").status_code == 404
