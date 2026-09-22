# EBITDA Improvement Engine

An AI diagnostic that finds **structural, pipeline-safe cost opportunities** in
a **biotechnology or pharmaceutical** company. It benchmarks the company's cost
structure against real US public biotech and pharma SEC filers, then interviews
leadership to establish which gaps are structural, and records each opportunity
with the reason and a first step. It does **not** estimate savings: it finds
where and why; sizing is a separate step with the company's finance team.

Built for CEOs, PE operating partners and transformation teams.

## Run it

Two terminals.

```powershell
# 1 — backend  (http://127.0.0.1:8010, API docs at /docs)
cd C:\projects-local\ebitda-engine\backend
python -m uvicorn main:app --port 8010

# 2 — frontend (http://localhost:5180)
cd C:\projects-local\ebitda-engine\frontend
npm run dev
```

Open **http://localhost:5180**. (Port 5173 on this machine is the older
pharma-bench app.)

The UI is a **single screen: the AI diagnostic**. Users never pick or name a
company:

1. **Choose Biotechnology or Pharmaceutical** in the top bar.
2. **Upload P&L**, or load one of two anonymous **sample P&Ls** (one per
   industry). A sample sets its own industry.
3. **Start diagnostic.** The agent opens with the cost areas furthest out of
   line and interviews from there. **Opportunities** in the header lists what
   it has recorded (action, reason, first step, where the cost ranks against
   peers); each reply carries a **✓ figures checked** badge.

Changing the industry or the P&L resets the conversation, because the agent's
figures were computed against the previous pair.

- Ports are 8010/5180, not the usual 8000/5173, because the pharma-bench app on
  this machine uses those. Vite runs with `strictPort`, so a clash fails loudly
  instead of silently moving to another port.
- Use `python -m uvicorn`; the Python scripts directory is not on PATH.
- `openpyxl` and `xlrd` are required for Excel uploads (`pip install -r
  backend/requirements.txt`); without `xlrd`, `.xls` files fail with an
  install hint rather than a traceback.
- The agent needs the `claude` CLI installed and signed in (it is on this
  machine). No API key is used. `GET /api/health` reports `claude_cli: true`
  when it is found.

### Tests

```powershell
cd backend ; python -m pytest tests -q     # 138 tests, no model calls
cd ..\frontend ; npm run build             # typecheck + production build
```

The agent tests use a scripted fake model, so the full loop — recording
opportunities, the dollar-figure guard and its retry, streaming, error
rollback — is tested without spending anything.

## Demo script

The **Specialty pharma · $480M** sample is the primary demo. The
**Commercial-stage biotech · $520M** sample is the R&D-protection moment. No
company name appears in the UI or reaches the model.

0. **Pharmaceutical** in the top bar. The context line shows how many US public
   companies back the comparison.
1. Click **Specialty pharma · $480M**.
2. **Start diagnostic**: the agent opens with G&A ($96.0M, about 20% of
   revenue, costlier than about 8 in 10 similar companies) and facilities,
   says this shows where to look rather than what can be saved, then asks its
   first question.
3. Answer from the **operator crib sheet** on the right of the conversation (the
   agent never sees it). E.g. *"Three bolt-on acquisitions each kept their own
   finance, HR, regulatory affairs and IT. G&A headcount is 260 of 1,150."*
4. The agent records an opportunity (consolidate the back offices, why, first
   step) and the **Opportunities** count in the header goes up. It should
   consolidate regulatory affairs rather than shrink it (compliance-critical).
5. Answer about sites (*"five sites; the New Jersey and Ohio offices are below
   40% occupancy"*). A second opportunity appears, and the agent offers an
   order: what to do first and what to leave alone. Ask *"how much could we
   save?"* — it should say sizing is a separate step, not guess.
6. **Commercial-stage biotech · $520M**. R&D is its largest line and above median. Start the diagnostic and
   ask it to cut R&D to reach breakeven faster — it should refuse: R&D is the
   pipeline.
7. **Upload P&L** with `samples/pharma_pl_line_items_thousands.csv` to show a
   real-format file: it detects line items in rows and figures in thousands,
   maps "Net Product Revenue" with confidence, reads revenue back as $310.0M
   before you commit, and flags the two "Memo:" lines as guesses. No company
   name is asked for; the industry is prefilled.

Each turn is one model call (two when the figure guard asks for a rewrite),
roughly $0.05 each on the CLI route.

## Uploading a P&L

**Read:** `.csv`, `.tsv`, `.xlsx`, `.xlsm`, `.xls` (Excel 97-2003, via `xlrd`),
`.ods`. Up to 15 MB. Either layout:

- **Line items down the rows, periods across the columns** — how most CFO
  exports look.
- **One column per line item, one row per period** — how system exports look.

**Refused, with instructions:** PDF, PowerPoint, Word, images, archives. The
engine reads figures cell by cell; inferring numbers from a slide or a scan is
how a misread digit becomes a confident wrong benchmark. See *Documents we do
not read* below.

The layout is detected, the mapping is *suggested* (low-confidence matches
flagged "guess"), and nothing is benchmarked until you confirm. Five traps are
handled, each of which would otherwise produce a confident wrong answer:

| Trap | Handling |
|---|---|
A workbook of many sheets | every sheet is scored on recognised line items and numeric density; the most P&L-like is read, the sheet is named on screen, and a selector re-parses another |
Figures "in thousands" | detected from the title; revenue is read back in dollars before you commit |
Expenses shown as negatives | cost lines normalised to positive; income lines keep their sign |
SG&A or EBITDA not in the file | derived exactly as for peers; EBITDA left blank if D&A is missing |
An unreadable format | named and refused ("PDF files are not supported..."), never partially parsed |

Drug-company wording is recognised: "Net product revenue" and "Total revenues"
map to revenue (never a single "Collaboration revenue" line), "Cost of product
sales" to cost of revenue.

No company name is asked for. The industry defaults to the one selected in the
top bar. Any P&L, upload or sample, is benchmarked against whichever industry is
currently selected (`?industry=` on the benchmark endpoint, `industry` when
starting a session). Two synthetic sample files are in `samples/`, one per
layout; they parse to identical figures.

### Documents we do not read

A P&L is the only document the engine ingests today. Everything else a
portfolio company would hand over — headcount rosters, AP and vendor spend,
licence inventories, lease schedules, board packs — has no public benchmark and
is gathered through the interview instead.

Adding them is the clearest next step, and the format decides the method:

| Document | Route |
|---|---|
Roster, AP file, licence list, lease schedule (CSV/Excel) | the existing deterministic pipeline: parse, confirm the mapping, aggregate in code |
Board pack, CIM (PDF/PPTX) | extract text and tables per page, retrieve on demand, and require a quote plus page citation that is checked against the extracted text |
Scanned statements, screenshots (PDF/image) | OCR or a vision model, then the same confirm-the-mapping step, with every value traceable to its page and cell |

The rule that must not bend: whatever the source, a figure reaches the model
only after code has parsed it and the user has confirmed what it means.

## How it works

### The model supplies judgment; code supplies arithmetic

This is the core design decision, and the reason the numbers can be trusted.

- **Benchmarks are computed in code** (`core/benchmarks.py`) before the model
  sees anything, and handed over as shares of revenue and ranks — the only peer
  figures it may cite. Dollar gaps to peers are deliberately withheld: they
  read as savings however they are labelled.
- **No savings are estimated.** The model records each opportunity (the
  action, the fact that explains it, a first step); code checks the cost area
  may be addressed at all and attaches where the company ranks against peers
  today, so the rank shown is the data's, not the model's.
- **A guard checks every dollar figure** in the reply against the P&L and what
  the user said. A savings estimate or a peer dollar gap matches neither, so it
  triggers one corrective retry; if it persists the reply is shown with the
  figure flagged, never silently.
- **Drug-industry rules in the prompt:** never cut R&D (it is the pipeline);
  field forces only for duplication; regulatory affairs, quality,
  pharmacovigilance and medical affairs may be consolidated but not shrunk
  below what approved products and trials require. Code refuses an R&D
  opportunity too, whatever the model proposes.

### Which cost areas are levers

Cost drivers overlap and play different roles. `core/drivers.py` gives each
driver an `ebitda_role`:

| Role | Drivers | Treatment |
|---|---|---|
lever | G&A, advertising | may be recorded as an opportunity |
lever_overlap | facilities | recorded; lease cost is allocated into G&A, so it can overlap |
rollup | SG&A | context only — it contains G&A, never a separate opportunity |
cash | CAPEX | recorded, marked as free cash flow, **never** EBITDA |
growth | R&D, sales & marketing | R&D never; sales & marketing only for duplication, marked as growth spend |
outcome | EBITDA margin | the result, not a lever |

The benchmark endpoint still computes dollar gap totals for other uses. There,
top-quartile targets count toward the upper bound only where peer data is
high-confidence: on thin peer sets p25 swings wildly — one test case produced a
+33-point margin "upside" before this rule. The diagnostic does not use them.

### Two industries, defined by company lists

**Biotechnology** and **Pharmaceutical** membership comes from the two company
lists in `C:\projects-local\data` (`Drugs_Biotechnology_US_496.csv`,
`Drugs_Pharmaceutical_US_228.csv`), resolved to SEC CIKs. SIC codes cannot make
this split: SEC files clinical-stage biotechs and large pharma alike under 2834.

**Peers need at least $10M revenue.** Most listed biotechs are pre-commercial:
below $10M, G&A runs at a median 64% of revenue and R&D at 61% — ratios that say
nothing about a commercial business's cost structure. A P&L under $10M is
compared with the nearest size band and says so.

### Peer selection

Size bands within two industries are thin (pharma $1–5B: 8 filers), so each
driver widens its own peer set until it has at least 20 usable values:

1. same industry, same size band, three most recent complete years
2. same industry and band, all years
3. same industry, neighbouring size bands
4. same industry, neighbouring bands, all years
5. biotech and pharma combined, same band
6. biotech and pharma combined, neighbouring bands, all years

Peers **never** leave biotech and pharma (tested). Every driver reports its `n`,
exactly which widenings its peer set used, and a confidence level: **high** needs
50+ same-industry values without neighbouring bands; neighbouring bands cap it at
**medium**; biotech and pharma combined is always **low** — their cost
structures differ (biotech R&D runs at several times pharma's).

Peers pool the three most recent complete fiscal years (FY2023–2025 for this
panel). The industry view and a P&L comparison use the same selection, so the
medians a user sees before uploading are exactly the ones their P&L is ranked
against (tested).

## Data

Built by four scripts in this directory:

| Script | Output |
|---|---|
`fetch_frames.py` | `data/frames_panel.csv` — 368,154 rows, 22 XBRL concepts × FY2019–2025, all SEC filers |
`build_sic_map.py` | `data/sic_map.csv` — 6,564 filers → SIC code, from DERA quarterly datasets |
`build_benchmarks.py` | `data/benchmarks.csv` — 46,463 company-years, EBITDA and cost ratios |
`build_industry_map.py` | `data/industry_map.csv` — 674 filers → biotech (479) or pharma (195), from the company lists |

At load, the engine keeps the listed companies with at least $10M revenue:
**299 companies, 1,348 company-years** (203 biotech, 96 pharma across all years;
166 and 84 in FY2023–2025).

`fetch_frames.py` uses the EDGAR **frames** API: one request returns a concept
for every filer. That is ~154 requests and 56 MB, against ~5,000 requests and
roughly 10 GB for a per-company download. EBITDA is derived as operating income
+ D&A and left blank where D&A is not tagged. `build_industry_map.py` reads the
CIKs already resolved by `C:\projects-local\data\fetch_edgar.py`.

Re-run only to refresh. Pass `--email you@domain` to `fetch_frames.py`; SEC asks
for a real contact in the User-Agent.

## Limitations — say these out loud in the demo

- **Peers are US public biotech and pharma companies.** Many are loss-making
  (biotech's typical EBITDA margin is −3.0% across sizes), so "above median" can
  still be poor for a PE-owned business. The agent is instructed to use top
  quartile as the bar.
- **Larger size bands are thin.** Pharma over $1B has fewer than 10 filers per
  band, so those comparisons widen and report medium or low confidence.
- **Only the listed companies.** 179 further SEC filers under drug SIC codes
  (2833–2836) are not on either list and are excluded, because their code
  cannot say whether they are biotech or pharma.
- **No public benchmark exists for headcount, technology spend, vendor spend or
  labor.** The agent gathers these by interview and uses them to explain a
  benchmarked gap, never as a peer comparison.
- **No savings figure.** The diagnostic says where and why a cost is out of
  line and what to do first; it does not say what that is worth. Closing
  either sample's G&A gap to median would mean removing almost 30% of its
  G&A, which is why a benchmark gap is never presented as a saving.
- **Sample P&Ls are synthetic.** Their cost problems are planted relative to
  real peer distributions so the demo reliably finds something genuine.
- **Latency.** A turn is one model call; the reply streams as it is written.
- **No database.** Benchmarks are CSVs loaded into memory at startup (static
  reference data). Uploaded P&Ls and chat sessions live in memory only: nothing
  a user uploads is written to disk, and all of it is lost when the backend
  restarts. Production would move uploads and sessions to a database.

## Layout

```
fetch_frames.py  build_sic_map.py  build_benchmarks.py  build_industry_map.py
data/
samples/             two synthetic pharma P&L files, one per layout
backend/
  main.py            FastAPI
  config.py          ports, peer thresholds, $10M peer floor, CLI settings + tool deny list
  core/
    drivers.py       driver registry and ebitda_role rules
    benchmarks.py    peer selection, comparison, correctly-built totals
    industries.py    Biotechnology and Pharmaceutical
    companies.py     sample + uploaded P&L registry, industry views
    ingest.py        P&L parsing: layout, units, signs, mapping
    portcos.py       the two synthetic sample P&Ls
    llm.py           claude CLI transport, inference only
    agent.py         interview loop, opportunities, dollar guard
  tests/             138 tests
frontend/src/
  App.tsx            industry → P&L flow, tabs, session state
  api.ts  types.ts  format.ts
  components/
    Chat.tsx           the whole UI: conversation, savings strip, empty states
    IndustryToggle.tsx  SamplePicks.tsx  Briefing.tsx  UploadDialog.tsx
    GetStarted.tsx  dashboard/   NOT BUILT IN -- the earlier dashboard and
                     industry-benchmark screens, kept on disk but no longer
                     imported, so they are absent from the bundle
```

The benchmark and industry-profile endpoints still exist and are tested; the
chat-only UI simply does not call them.

## Security note

The agent reads user-supplied financials, so a prompt injection hidden in that
data must not reach a shell or the filesystem. The CLI runs as pure inference:
every built-in Claude Code tool is denied (`config.CLAUDE_CLI_DISALLOWED_TOOLS`,
mirroring bitsy's list), the permission mode stays `default` rather than
`bypassPermissions` so an unlisted tool fails closed, and the API key is
stripped from the child environment.
