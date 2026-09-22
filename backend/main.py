"""FastAPI application for the EBITDA Improvement Engine.

Endpoints that touch the model are plain `def`, not `async def`: a CLI call
takes 5-25s and blocks, so FastAPI runs these in its threadpool and one slow
agent turn does not freeze every other request.
"""

import json
import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import config
from core import (agent, benchmarks, companies, history, ingest, insights, llm,
                  mapper, rag, trends)
from core.drivers import DRIVERS, UNBENCHMARKABLE

# A P&L is tiny, but a real workbook carries formatting, extra sheets and
# charts; 5 MB rejected ordinary .xls files from finance teams.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# Below this many recognised line items, ask the model to name the rest.
MIN_AUTOMAP_FIELDS = 4

# The only two industries benchmarked; FastAPI rejects anything else with 422.
Industry = Literal["biotech", "pharma"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    df = benchmarks.load_panel()
    print(f"benchmarks loaded: {len(df):,} company-years, "
          f"{df['cik'].nunique():,} filers, {df['sic'].nunique()} SIC codes")
    # Saved P&Ls come back into memory so their diagnostics can be reopened.
    # Sessions are restored lazily, when one is opened or continued.
    saved = history.load_companies()
    for c in saved:
        companies.restore_uploaded(c)
    print(f"chat history: {len(saved)} saved P&Ls in {config.HISTORY_DIR}")
    yield


app = FastAPI(
    title="EBITDA Improvement Engine",
    description=(
        "Benchmarks a biotechnology or pharmaceutical company's cost structure "
        "against US public SEC filers "
        "and runs a conversational diagnostic that finds structural, "
        "growth-safe cost opportunities - where, why and what to do, without "
        "estimating savings. Benchmark figures are computed in code; the "
        "model supplies judgment only."),
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartSession(BaseModel):
    company_id: str
    # The industry the user selected. Omitted, the P&L's own industry is used.
    industry: Optional[Industry] = None


class SendMessage(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class CreateFromUpload(BaseModel):
    upload_id: str
    # Carry org documents over from the company the user was just working on.
    # A new upload starts with an empty document store otherwise, which reads
    # as the agent "forgetting" context it was given moments earlier.
    carry_context_from: Optional[str] = None
    mapping: dict[str, Optional[str]]
    period: str
    units: Literal["dollars", "thousands", "millions"] = "dollars"
    name: Optional[str] = Field(None, max_length=80)
    industry: Industry
    fiscal_year: int = Field(..., ge=2015, le=2030)


class CreateAdjustment(BaseModel):
    description: str = Field(..., min_length=1, max_length=100)
    amount: float
    driver: str = Field(..., min_length=1)


def _company_or_404(company_id: str) -> dict:
    c = companies.get(company_id)
    if c is None:
        raise HTTPException(404, f"Unknown company '{company_id}'. Upload the "
                                 f"P&L again.")
    return c


def _view(company_id: str, industry: Optional[str]) -> dict:
    c = _company_or_404(company_id)
    return companies.in_industry(c, industry) if industry else c


def _llm_failure(e: Exception) -> HTTPException:
    # The hint has to follow the live transport: pointing an Azure failure at
    # the `claude` CLI sends people to debug a binary the call never touched.
    if config.LLM_PROVIDER == "azure":
        hint = ("Check AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT and "
                "AZURE_OPENAI_API_KEY in backend/.env, and restart the server "
                "so it reloads them.")
    else:
        hint = "Check that the `claude` CLI is installed and signed in."
    return HTTPException(502, f"The diagnostic model call failed: {e}. {hint}")


# --- meta ----------------------------------------------------------------------

@app.get("/api/health", tags=["meta"])
def health():
    df = benchmarks.load_panel()
    try:
        claude = bool(llm.find_claude_bin())
    except llm.LLMError:
        claude = False
    return {"status": "ok", "company_years": len(df),
            "filers": int(df["cik"].nunique()),
            "claude_cli": claude, "model": config.CLAUDE_CLI_MODEL,
            "llm_provider": config.LLM_PROVIDER,
            "azure_configured": bool(config.AZURE_OPENAI_ENDPOINT
                                    and config.AZURE_OPENAI_DEPLOYMENT
                                    and config.AZURE_OPENAI_API_KEY)}


@app.get("/api/meta", tags=["meta"])
def meta():
    return {
        "drivers": [d.as_dict() for d in DRIVERS.values()],
        "unbenchmarkable": UNBENCHMARKABLE,
        "revenue_bands": benchmarks.PEER_BANDS,
        "peer_min_revenue": config.PEER_MIN_REVENUE,
        "min_peers": config.MIN_PEERS,
        "pool_years": config.POOL_YEARS,
        "model": config.CLAUDE_CLI_MODEL,
        "upload_fields": [{"key": k, "label": v[0], "required": k == "revenue"}
                          for k, v in ingest.FIELDS.items()],
    }


@app.get("/api/industries", tags=["meta"])
def industries():
    return {"results": benchmarks.industries(),
            "reference_year": benchmarks.reference_year()}


@app.get("/api/industries/{industry}/profile", tags=["benchmark"])
def industry_profile(industry: Industry, band: Optional[str] = Query(None)):
    """An industry's cost structure: p10-p90 per driver. No company, no model."""
    try:
        return benchmarks.industry_profile(industry, band or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# --- companies -----------------------------------------------------------------

@app.get("/api/companies", tags=["companies"])
def list_companies():
    return {"results": companies.list_all()}


@app.get("/api/companies/{company_id}", tags=["companies"])
def company_detail(company_id: str):
    c = _company_or_404(company_id)
    return {**companies.summary(c), "financials": c["financials"]}


@app.post("/api/companies/{company_id}/adjustments", tags=["companies"])
def add_company_adjustment(company_id: str, payload: CreateAdjustment):
    c = companies.add_adjustment(company_id, payload.description, payload.amount, payload.driver)
    if not c:
        raise HTTPException(404, f"Unknown company '{company_id}'.")
    return {**companies.summary(c), "financials": c["financials"]}


@app.get("/api/companies/{company_id}/briefing", tags=["companies"])
def company_briefing(company_id: str):
    """Demo-operator crib sheet. Never sent to the model.

    Only synthetic companies have one; for an upload, the user IS the source
    of those facts.
    """
    c = _company_or_404(company_id)
    return {"id": c["id"], "name": c["name"],
            "hidden_facts": c.get("hidden_facts", {}),
            "planted": c.get("planted", {})}


@app.get("/api/companies/{company_id}/benchmark", tags=["benchmark"])
def company_benchmark(company_id: str, industry: Optional[Industry] = Query(None)):
    """Deterministic comparison only -- no model call, returns instantly.

    `industry` benchmarks the P&L against the industry the user selected.
    """
    c = _view(company_id, industry)
    return benchmarks.compare_company(c["financials"], c["industry"],
                                      c["fiscal_year"])


# --- org context (RAG) ---------------------------------------------------------

def _doc_summary(d) -> dict:
    return {"id": d.id, "filename": d.filename, "chunks": d.chunks,
            "chars": d.chars, "uploaded_at": d.uploaded_at}


@app.get("/api/companies/{company_id}/documents", tags=["documents"])
def list_documents(company_id: str):
    """Org documents indexed for this company, plus whether RAG is usable."""
    _company_or_404(company_id)
    return {"configured": rag.configured(),
            "accepted": list(rag.SUFFIXES),
            "results": [_doc_summary(d) for d in rag.documents(company_id)]}


@app.post("/api/companies/{company_id}/documents", tags=["documents"])
async def upload_document(company_id: str, file: UploadFile = File(...)):
    """Index one org document so the diagnostic can cite it.

    This is the qualitative counterpart to /api/uploads, which reads a P&L for
    its numbers. Nothing here is parsed into financials -- the text is chunked
    and embedded so the agent can ground a lever in an actual operating fact.
    """
    _company_or_404(company_id)
    content = await file.read()
    try:
        doc = rag.index_document(company_id, content,
                                 file.filename or "document")
    except rag.RagError as e:
        raise HTTPException(400, str(e)) from e
    return _doc_summary(doc)


@app.delete("/api/companies/{company_id}/documents/{doc_id}", tags=["documents"])
def delete_document(company_id: str, doc_id: str):
    _company_or_404(company_id)
    try:
        if not rag.delete_document(company_id, doc_id):
            raise HTTPException(404, f"Unknown document '{doc_id}'.")
    except rag.RagError as e:
        raise HTTPException(400, str(e)) from e
    return {"deleted": doc_id}


@app.get("/api/companies/{company_id}/documents/search", tags=["documents"])
def search_documents(company_id: str, q: str = Query(..., min_length=1),
                     top_k: int = Query(5, ge=1, le=20)):
    """Retrieval preview -- what the agent would see for this query."""
    _company_or_404(company_id)
    try:
        return {"results": rag.search(company_id, q, top_k)}
    except rag.RagError as e:
        raise HTTPException(400, str(e)) from e


# --- upload --------------------------------------------------------------------

@app.post("/api/uploads", tags=["upload"])
async def upload_preview(file: UploadFile = File(...),
                         sheet: Optional[str] = Form(None)):
    """Parse a P&L and SUGGEST a mapping. Nothing is benchmarked yet.

    `sheet` overrides which worksheet is read; by default the sheet that looks
    most like a P&L wins.
    """
    content = await file.read()
    if not content:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"File too large: {len(content) / 1e6:.1f} MB. The limit is "
                 f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        preview = ingest.parse_upload(content, file.filename or "upload.csv",
                                      sheet=sheet)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    # Real exports rarely match a synonym list exactly. When the obvious lines
    # are missing, one model call names them -- judgment only; every figure is
    # still read, scaled and benchmarked in code, and the user sees what was
    # mapped before anything is benchmarked.
    mapping = preview["suggested_mapping"]
    preview["ai_mapped"] = []
    if not mapping.get("revenue") or len(mapping) < MIN_AUTOMAP_FIELDS:
        guessed = mapper.suggest(
            preview["labels"],
            {k: v[0] for k, v in ingest.FIELDS.items()},
            ingest.label_samples(preview["upload_id"], preview["default_period"]))
        for field, label in guessed.items():
            if field not in mapping:
                mapping[field] = {"label": label, "confidence": "ai"}
                preview["ai_mapped"].append(field)
    return preview


class TrendRequest(BaseModel):
    upload_id: str
    mapping: dict[str, Optional[str]]
    units: Literal["dollars", "thousands", "millions"] = "dollars"


@app.post("/api/uploads/trend", tags=["upload"])
def upload_trend(body: TrendRequest):
    """EBITDA across every period in the upload, with chart data and commentary.

    /api/uploads/company collapses a multi-period file to the one period being
    benchmarked. This keeps the series, so a file with four quarters answers
    "which way is this going" as well as "where does it sit against peers".
    """
    try:
        return trends.analyse(body.upload_id, body.mapping, body.units)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/uploads/company", tags=["upload"])
def upload_create_company(body: CreateFromUpload):
    """Apply the CONFIRMED mapping and register the company."""
    try:
        extracted = ingest.extract(body.upload_id, body.mapping, body.period,
                                   body.units)
        company = companies.create_uploaded(
            body.name, body.industry, body.fiscal_year, extracted["financials"],
            source=ingest._UPLOADS[body.upload_id]["filename"])
        # Record EVERY period in the file, not just the one being benchmarked.
        # The benchmark needs a single snapshot; "how are we holding up" needs
        # the series, and discarding it here is why there was never a prior
        # period to average against.
        _record_upload_periods(company["id"], body.upload_id, body.mapping,
                               body.units)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    # The trend is kept on the company so a diagnostic reopened from history
    # still has its chart; the upload it came from expires with the process.
    company["trend"] = _upload_trend_or_none(body.upload_id, body.mapping,
                                             body.units)
    # A replacement P&L is the same business, so the headcount entered for the
    # previous one comes across with it, as its documents do below.
    if body.carry_context_from:
        prev = companies.get(body.carry_context_from)
        if prev and prev.get("headcount"):
            company["headcount"] = dict(prev["headcount"])
    _save_company(company)

    # Best-effort: a retrieval outage must not stop the P&L being benchmarked.
    carried = 0
    if body.carry_context_from:
        try:
            carried = rag.copy_documents(body.carry_context_from, company["id"])
        except rag.RagError:
            carried = 0

    return {"company": companies.summary(company),
            "financials": company["financials"],
            "missing_labels": extracted["missing_labels"],
            "ebitda_history": companies.ebitda_history(company["id"]),
            "trend": company["trend"],
            "documents_carried": carried}


def _upload_trend_or_none(upload_id: str, mapping: dict, units: str):
    """The multi-period trend, or None for a single-period file.

    One period has nothing before it to average, so a "trend" of one bar
    measured against itself would only mislead.
    """
    try:
        t = trends.analyse(upload_id, mapping, units)
    except (ValueError, KeyError):
        return None
    return t if len(t["periods"]) >= 2 else None


def _save_company(company: dict) -> None:
    """Best-effort: a full disk must not stop the P&L being benchmarked."""
    try:
        history.save_company(company, time.time())
    except OSError as e:
        print(f"chat history: could not save company {company['id']}: {e}")


def _record_upload_periods(company_id: str, upload_id: str, mapping: dict,
                           units: str) -> None:
    """Best-effort: a file whose periods cannot be read still benchmarks fine."""
    try:
        rows = trends.series(upload_id, mapping, units)
    except (ValueError, KeyError):
        return
    companies.record_periods(company_id, [
        {"period": r["period"], "ebitda": r["ebitda"], "revenue": r["revenue"]}
        for r in rows if r["ebitda"] is not None
    ])


class AddPeriods(BaseModel):
    upload_id: str
    mapping: dict[str, Optional[str]]
    units: Literal["dollars", "thousands", "millions"] = "dollars"


@app.get("/api/companies/{company_id}/ebitda-history", tags=["companies"])
def company_ebitda_history(company_id: str):
    """Recorded periods plus the average of everything before the latest."""
    _company_or_404(company_id)
    return companies.ebitda_history(company_id)


class Headcount(BaseModel):
    total_fte: float = Field(..., gt=0, le=10_000_000)
    sga_fte: Optional[float] = Field(None, ge=0, le=10_000_000)


@app.get("/api/companies/{company_id}/insights", tags=["companies"])
def company_insights(company_id: str, industry: Optional[Industry] = Query(None)):
    """Eight overhead and productivity ratios against (placeholder) benchmarks."""
    c = _company_or_404(company_id)
    return insights.compute(c, industry or c["industry"])


@app.put("/api/companies/{company_id}/headcount", tags=["companies"])
def set_company_headcount(company_id: str, body: Headcount,
                          industry: Optional[Industry] = Query(None)):
    """Headcount is not on a P&L, so the user supplies it once per company."""
    c = _company_or_404(company_id)
    if body.sga_fte is not None and body.sga_fte > body.total_fte:
        raise HTTPException(422, "SG&A employees cannot exceed total employees.")
    c["headcount"] = {"total_fte": body.total_fte, "sga_fte": body.sga_fte}
    if c.get("uploaded"):
        _save_company(c)
    return insights.compute(c, industry or c["industry"])


@app.post("/api/companies/{company_id}/periods", tags=["companies"])
def add_company_periods(company_id: str, body: AddPeriods):
    """Add a newer P&L to an EXISTING company rather than making a new one.

    This is what makes the average accumulate: the same business gains periods
    over time, so each upload is measured against everything recorded before.
    """
    company = _company_or_404(company_id)
    try:
        _record_upload_periods(company_id, body.upload_id, body.mapping,
                               body.units)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if company.get("uploaded"):
        _save_company(company)
    return companies.ebitda_history(company_id)


# --- agent ---------------------------------------------------------------------

def _record_turn(session_id: str, user_text: Optional[str], sent_at: float,
                 payload: dict) -> None:
    """Add the finished turn to the transcript and save the diagnostic.

    Called only once a turn has completed, so a failed turn (which the agent
    rolls back) never reaches the saved file. Saving is best-effort: a disk
    problem must not cost the user the reply they are waiting for.
    """
    s = agent.get_session(session_id)
    if s is None:
        return
    if user_text is not None:
        s.transcript.append({"role": "user", "content": user_text,
                             "at": sent_at})
    s.transcript.append({"role": "assistant", "content": payload["message"],
                         "guard": payload["guard"], "at": time.time()})
    try:
        history.save_session(s, time.time())
    except OSError as e:
        print(f"chat history: could not save session {s.id}: {e}")


def _session_or_404(session_id: str) -> agent.Session:
    """The live session, or the saved one brought back to life."""
    s = agent.get_session(session_id)
    if s is not None:
        return s
    state = history.load_session(session_id)
    if state is None:
        raise HTTPException(404, "This diagnostic was not found. It may have "
                                 "been deleted; start a new one.")
    return agent.restore_session(state)


@app.post("/api/sessions", tags=["agent"])
def start_session(body: StartSession):
    c = _view(body.company_id, body.industry)
    started = time.time()
    try:
        s, opening = agent.start_session(c)
    except llm.LLMError as e:
        raise _llm_failure(e) from e
    _record_turn(s.id, None, started, opening)
    return opening


def _sse(events, session=None, user_text: Optional[str] = None,
         sent_at: float = 0.0) -> StreamingResponse:
    """Wrap an agent event generator as server-sent events.

    Errors are delivered as a final `error` event rather than raised: the
    response status is long since committed by the time a model call fails, so
    an exception here would just truncate the stream and leave the browser
    showing a half-written reply with no explanation.
    """
    def body():
        try:
            for ev in events:
                if ev.get("type") == "done":
                    # Saved before the client hears the turn is done, so a
                    # history refresh straight after always includes it.
                    _record_turn(ev["payload"]["session_id"], user_text,
                                 sent_at, ev["payload"])
                yield f"data: {json.dumps(ev)}\n\n"
        except llm.LLMError as e:
            if session is not None:
                session.discard_last_user()
            detail = _llm_failure(e).detail
            yield f"data: {json.dumps({'type': 'error', 'text': detail})}\n\n"
        except Exception as e:  # noqa: BLE001 - the stream must always close
            if session is not None:
                session.discard_last_user()
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(body(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        # Without this a proxy buffers the whole stream and defeats the point.
        "X-Accel-Buffering": "no",
    })


@app.post("/api/sessions/stream", tags=["agent"])
def start_session_stream(body: StartSession):
    """Open a session and stream the opening turn."""
    c = _view(body.company_id, body.industry)
    return _sse(agent.start_session_stream(c), sent_at=time.time())


@app.post("/api/sessions/{session_id}/messages/stream", tags=["agent"])
def send_message_stream(session_id: str, body: SendMessage):
    s = _session_or_404(session_id)
    text = body.text.strip()
    return _sse(s.turn_stream(text), session=s, user_text=text,
                sent_at=time.time())


@app.post("/api/sessions/{session_id}/messages", tags=["agent"])
def send_message(session_id: str, body: SendMessage):
    s = _session_or_404(session_id)
    text = body.text.strip()
    sent_at = time.time()
    try:
        turn = s.turn(text)
    except llm.LLMError as e:
        s.discard_last_user()
        raise _llm_failure(e) from e
    except Exception as e:  # noqa: BLE001 - a dead turn must not poison the session
        s.discard_last_user()
        raise HTTPException(502, f"The diagnostic failed mid-turn: {e}") from e
    _record_turn(s.id, text, sent_at, turn)
    return turn


@app.get("/api/sessions", tags=["agent"])
def list_sessions():
    """Saved diagnostics, most recently active first."""
    return {"results": history.list_sessions()}


@app.get("/api/sessions/{session_id}", tags=["agent"])
def get_session(session_id: str):
    """Everything needed to reopen a diagnostic where it was left."""
    s = _session_or_404(session_id)
    company = companies.get(s.portco["id"]) or s.portco
    # The session was diagnosed against one industry; show it that way even
    # if the stored company carries another.
    view = companies.in_industry(company, s.portco["industry"])
    return {
        "session_id": s.id,
        "company_id": s.portco["id"],
        "company": companies.summary(view),
        "industry": s.portco["industry"],
        "messages": s.transcript,
        "trend": company.get("trend"),
        "history": s.history,
        "facts": s.facts,
        "findings": s.findings,
        "findings_totals": s.findings_totals(),
        "comparison": s.comparison,
        "total_cost_usd": round(sum(t["cost_usd"] for t in s.trace), 4),
        "model_calls": len(s.trace),
    }


@app.delete("/api/sessions/{session_id}", tags=["agent"])
def delete_session(session_id: str):
    agent.forget_session(session_id)
    if not history.delete_session(session_id):
        raise HTTPException(404, "This diagnostic was not found.")
    return {"deleted": session_id}
