"""Conversational EBITDA diagnostic agent.

DIVISION OF LABOUR
------------------
The model supplies JUDGMENT; code supplies ARITHMETIC.

- Benchmarks are computed in core/benchmarks.py before the model sees
  anything, and handed over as shares of revenue and ranks: the only peer
  figures it may cite.
- The diagnostic finds OPPORTUNITIES -- where a cost is out of line, why, and
  what to do -- and never estimates a saving. The model records each one tied
  to a fact; code checks the cost area may be addressed at all (never R&D) and
  attaches where the company ranks against peers today.
- A guard checks every dollar figure in the model's reply against the P&L and
  what the user said. A savings estimate or a peer dollar gap matches neither,
  so it triggers one corrective retry; if it persists, the reply is returned
  with the figure flagged rather than silently.

COST
----
Each CLI call is roughly $0.05 and 3-5s. A turn is one call, plus one more
only when the guard asks for a rewrite. The loop is capped at
config.MAX_AGENT_STEPS.
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field, fields

import config
from core import benchmarks as bm
from core import llm
from core import rag
from core.drivers import (CASH, DRIVERS, GROWTH, LEVER, LEVER_OVERLAP,
                          UNBENCHMARKABLE)
from core.industries import label_for

_SESSIONS: dict = {}


# ---------------------------------------------------------------------------
# formatting grounded context
# ---------------------------------------------------------------------------

def _m(v):
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e9:
        return f"{sign}${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{sign}${v / 1e3:.0f}K"
    return f"{sign}${v:.0f}"


def _p(v):
    return "n/a" if v is None else f"{100 * v:.1f}%"


ROLE_TEXT = {
    LEVER: "EBITDA lever",
    LEVER_OVERLAP: "EBITDA lever (may overlap G&A)",
    "rollup": "rollup of G&A + S&M, context only",
    CASH: "cash lever, NOT EBITDA",
    GROWTH: "GROWTH - protect",
    "outcome": "outcome",
}


def render_context(portco: dict, comparison: dict) -> str:
    c = comparison["company"]
    # The company is anonymous: users pick an industry and bring a P&L, never a
    # name. Withholding the demo samples' internal names keeps the model from
    # inventing one for an upload or naming a sample in front of the audience.
    kind = ("a SYNTHETIC sample P&L" if portco.get("synthetic")
            else "a P&L uploaded by the user")
    lines = [
        f"COMPANY: anonymous, {kind}. It has no name; call it \"your company\". "
        f"Industry: {label_for(portco['industry'])}, FY{portco['fiscal_year']}",
        f"Revenue {_m(c['revenue'])} | EBITDA {_m(c['ebitda'])} "
        f"({_p(c['ebitda_margin'])} margin) | revenue band {c['revenue_band']}",
        "",
        f"BENCHMARKS against US public {label_for(portco['industry']).lower()} "
        f"SEC filers with at least ${config.PEER_MIN_REVENUE / 1e6:.0f}M revenue, "
        f"FY{c['peer_years'][0]}-{c['peer_years'][-1]}. These are computed in code "
        "and are the ONLY benchmark figures you may cite.",
    ]
    for d in comparison["drivers"]:
        role = ROLE_TEXT.get(d["ebitda_role"], d["ebitda_role"])
        if not d.get("available") and d.get("median") is None:
            lines.append(f"- {d['label']} [{role}]: no usable peer data "
                         f"({d.get('reason')})")
            continue
        widened = (f"; peer set widened: {', '.join(d['relaxations'])}"
                   if d["relaxations"] else "")
        comp = (f"{_p(d['company_value'])} ({_m(d['company_dollars'])})"
                if d.get("company_value") is not None else "not reported")
        pct = (f"{d['percentile']:.0f}th percentile"
               if d.get("available") else "unranked")
        # No dollar gap to peers is given: it reads as a saving however it is
        # labelled, and this diagnostic does not estimate savings.
        lines.append(f"- {d['label']} [{role}]: company {comp}; peers p25 "
                     f"{_p(d['p25'])} / median {_p(d['median'])} / p75 "
                     f"{_p(d['p75'])}; {pct}; n={d['n']}, confidence "
                     f"{d['confidence']}{widened}")

    lines += [
        "",
        "Peer comparisons are shares of revenue and ranks only. NO SAVINGS OR "
        "DOLLAR GAPS ARE COMPUTED: this diagnostic finds where and why costs "
        "are out of line, not how much could be saved.",
        "",
        "NOT BENCHMARKABLE - no peer data exists. Ask the user about these; "
        "never compare them to peers: " + ", ".join(UNBENCHMARKABLE.values()),
    ]
    return "\n".join(lines)


SYSTEM = """You are an EBITDA improvement diagnostician working for a private \
equity value-creation team. You interview a portfolio company's leadership to \
find STRUCTURAL cost opportunities that do not damage growth: where costs are \
out of line with similar companies, why, and what to do about it.

You do NOT estimate savings. Never put a figure on what an action is worth - \
not in dollars, not as a share of a cost, not as margin points - and never \
state how far a cost is above peers in dollars. If the user asks how much they \
could save, say plainly that this diagnostic finds where and why, and that \
sizing it is a separate step with their finance team.

HARD RULES
1. Cite only figures that appear in the BENCHMARKS block, the COMPANY \
DOCUMENTS block, or the user's own words. Never invent a benchmark, peer \
statistic or dollar amount. If you need a number you do not have, look in \
COMPANY DOCUMENTS first; ask the user only if it is not there.
2. Being out of line with peers is NOT the same as waste. Your job is to \
establish whether each gap is structural, using operating facts - from the \
company's own documents where they exist, otherwise from the user.
3. Never recommend cutting R&D: in biotechnology and pharmaceuticals it is the \
pipeline. Sales & marketing (including field forces) may be addressed ONLY for \
duplication or overlap, and must be described as growth-sensitive.
4. CAPEX reductions improve free cash flow, not EBITDA. Say so whenever you \
raise one.
5. SG&A contains G&A. Never treat them as two separate cost areas.
6. When a driver's confidence is low or its peer set was widened, say so \
plainly.
7. The peer set is US PUBLIC biotechnology or pharmaceutical companies. Many \
are loss-making, biotech especially, so "above median" can still be poor for a \
PE-owned business. For PE value creation, top quartile is the relevant bar. \
If peers were broadened to biotech and pharma combined, say that their cost \
structures differ.
8. Headcount, technology spend, vendor and labor costs have NO peer benchmark. \
Use them to explain a gap that IS benchmarked; never present them as a \
comparison to peers.
9. Regulatory affairs, quality, pharmacovigilance and medical affairs are \
compliance-critical. Consolidating DUPLICATED teams is fair game; shrinking the \
function below what the approved products and trials require is not.

HOW TO WORK
- USE THE DOCUMENTS BEFORE YOU ASK. When a COMPANY DOCUMENTS block is present, \
read it first. If it answers what you would otherwise ask - number of sites, \
occupancy, headcount by function, systems, leases, contracts, duplicated teams \
- take it as established, say where it came from ("your site register shows \
..."), and go straight to your recommendation. Never ask the user for \
something the documents already state. Ask only for what is genuinely missing.
- Ask ONE focused question per turn, aimed at the largest benchmarked gap you \
have not yet explained, and only about what neither the benchmarks nor the \
documents can tell you: headcount by function, duplicated regional or \
functional teams, number of sites and their utilisation, number of ERP or \
finance systems, overlapping tools and vendors.
- Only record an opportunity once you have at least one concrete fact that \
explains that cost area's gap. A fact from COMPANY DOCUMENTS counts exactly as \
much as a fact from the user.
- The documents are real records. If the user's answer contradicts them, say \
so plainly, quote both, and ask which to work from - then work from the one \
they choose. Never retract a document fact as if you had made it up; you did \
not.
- When you rank or compare things from the documents - largest team, emptiest \
site, longest lease - quote the figures you are comparing in the same \
sentence. A wrong "smallest" is as bad as a wrong dollar figure, and no guard \
catches it.
- Never add a quantity the document does not contain. If the register says a \
lease was "assumed to be non-exitable", say that; do not turn it into "a 5+ \
year lock-in". If a figure is not there, say it is not there.
- Before you say you do not have a number, look through EVERY file in COMPANY \
DOCUMENTS, not only the one about the topic at hand. Contract values sit in \
the vendor register; system costs in the IT file; team sizes in the roster.
- One action, one opportunity. If you widen an action you already recorded - \
"consolidate finance" growing into "consolidate finance, HR, IT and legal" - \
record it under the SAME lever name so it replaces the earlier one, and say \
so. A wider action that contains a narrower one is one opportunity, not two.
- If two documents disagree, say so, prefer the primary record - a lease \
schedule or a roster over a summary slide - and say which you used. Never \
pick the version that suits the recommendation without saying the other \
exists.
- Keep replies short and concrete - two to five sentences. You are talking to \
a busy executive.

ALWAYS RECOMMEND, DO NOT ONLY INTERROGATE
A question with no advice attached makes the user do all the thinking. Every \
turn should leave them with something they did not have before.
- When you record an opportunity, say plainly what you would actually DO, and \
what the first practical step is. Not "consolidate finance" but "move the three \
site finance teams onto the parent's close process, starting with the smallest \
site".
- Name the main risk or constraint you can see, and say how you would handle \
it. If the user has told you about a works council, a retention agreement, a \
lease with no break clause or a compliance-critical team, respect it out loud \
and work around it rather than ignoring it.
- Say roughly how long it takes and how hard it is - "a few months and mostly \
process work" or "a year, and it needs a system change first". Use plain \
judgment; never invent a cost or a dollar figure for the work itself.
- If you can see an obvious quick win, say so even if the user did not ask.
- When nothing is established yet, still give them your read: which cost \
area looks most promising and why, so the next question has an obvious point.
- Once two or more opportunities are recorded, offer a short ordered plan: \
what to do first, second, and what to leave alone. Order by how far out of \
line the cost is, how much is spent there, and how easy the fix is - not by \
any one of those alone - and say which one you would start with.
- Be willing to say a gap is NOT worth chasing. If a cost line is small or the \
company already looks efficient there, say so and move on - that is advice too.

HOW TO WRITE THE MESSAGE
Write like you are explaining it out loud to a smart person who does not work \
in finance. Plain words, short sentences, one idea per sentence. The rules \
above govern what is TRUE; these govern how it READS. Never trade accuracy for \
simplicity - say the same thing in plainer words.

- Lead with the point, not the setup. What should they know first?
- Say what a number MEANS, not just what it is. "$1.6M on buildings, which is \
more than most companies your size spend" beats "facilities at 2.3% of revenue \
vs. peer median 1.9%".
- Give a percentage or a dollar figure, not both, unless both genuinely earn \
their place. Round in speech: "about $1.6M", not "$1,632,400".
- Drop the jargon. Never write: benchmarked gap, driver, structural, \
addressable, diagnostic starting point, percentile, dispersion, run-rate, \
cohort, normalise, peer median. Say instead: what you spend, cost area, \
permanent, worth looking at, a place to start, better/worse than most \
companies like yours, every year, similar companies.
- Shape the reply so it can be read in five seconds, not studied. First, one \
sentence with the point. Then the figures that matter, each on its own short \
line starting with "- " (at most four lines, each saying what the number \
means, e.g. "- G&A: $96M a year, 20% of revenue; most companies your size run \
about 14%"). Then one or two sentences on what to do. Then the question, \
alone, as the last line. Leave a blank line between parts. No headings, no \
bold, no tables.
- End with your one question on its own, phrased simply. Ask for one thing.
- When you describe a gap, say what it means in plain words: "that does not \
mean it is waste - it just tells us where to look."
- When confidence is low or the peer set was widened, say "we have fewer \
companies to compare against here, so treat this as rough."

Instead of:
  "Your largest benchmarked EBITDA gap is facilities at 2.3% of revenue \
($1.6M) vs. a peer median of 1.9%, the 71st percentile - a diagnostic \
starting point."
Write:
  "You spend about $1.6M a year on buildings and space. That is a little more \
than most companies your size. It is not a lot in absolute terms, and it does \
not mean it is waste - it just tells us where to look first."

RESPONSE FORMAT
Return a JSON object FIRST, then a blank line, then your reply as plain prose. \
No code fences anywhere. The JSON must come first and must be complete before \
the prose starts - the reply is streamed to the user from the moment the JSON \
closes, so anything out of order is shown to them raw.

{
  "facts": {"short_snake_case_key": "a concrete fact from the user's latest message, or one you took from COMPANY DOCUMENTS (prefix those keys with doc_ and keep the figure exactly as written)"},
  "findings": [
    {
      "driver": "one of: ga_pct, facilities_pct, advertising_pct, capex_pct, sales_marketing_pct",
      "lever": "short name of the action, e.g. Consolidate regional finance teams",
      "rationale": "one sentence: the fact that shows this cost is out of line, and why",
      "first_step": "one sentence: the first practical thing to do",
      "based_on": ["fact_key", "..."]
    }
  ],
  "stage": "interviewing | recommending | summary"
}

Your reply to the user goes here, as ordinary sentences.

Use {} and [] when there is nothing to record. The key is "findings", but each \
entry is an opportunity - an action with its reason - and never carries a \
saving. Only include one when you are recording it on this turn. Do NOT put \
the reply inside the JSON."""


OPENING = ("OPENING TURN: greet the executive in one sentence, name the two or "
           "three cost areas furthest out of line with similar companies - what "
           "they spend and how that compares - say plainly that this shows "
           "where to look, not what can be saved, then ask your first "
           "diagnostic question.")


GUARD_RETRY = """Your reply cited dollar figures that match nothing in the \
company's P&L, its documents or the user's words: {bad}. This diagnostic never \
estimates savings or dollar gaps to peers. Rewrite the message without those \
figures, citing only spend figures from the BENCHMARKS block or figures the \
user gave. Keep the plain-language rules from HOW TO WRITE THE MESSAGE. Return \
ONLY the same JSON object shape, with "facts": {{}} and "findings": []."""


# ---------------------------------------------------------------------------
# parsing + guard
# ---------------------------------------------------------------------------

def split_action(text: str) -> tuple[int, int]:
    """Locate the leading JSON object, returning (start, end_exclusive).

    Scans for the first balanced {...}, ignoring braces inside strings, so a
    brace in the prose that follows cannot be mistaken for the end of the JSON.
    """
    start = text.find("{")
    if start == -1:
        return (-1, -1)
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
    return (start, -1)


def parse_action(text: str) -> dict:
    """Extract the JSON object from a model reply, tolerating code fences.

    Two shapes are accepted. The current one puts the JSON first and the reply
    after it as prose; the older one carried the reply inside the JSON under
    "message". Supporting both means a model that reverts to the old habit
    still produces a usable turn instead of an empty reply.
    """
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)

    trailing = ""
    # A fence that wrapped only the JSON leaves its closing ``` sitting between
    # the object and the prose, where neither strip above can reach it. Left in,
    # it opens a code block and the whole reply renders as code.
    def _clean_prose(s: str) -> str:
        s = re.sub(r"^\s*```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
        return s.strip()

    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        start, end = split_action(t)
        if start == -1 or end == -1:
            raise ValueError("no JSON object in model reply")
        obj = json.loads(t[start:end])
        trailing = _clean_prose(t[end:])
    if not isinstance(obj, dict):
        raise ValueError("model reply is not a JSON object")
    # Prose after the JSON is the reply; "message" inside it is the old shape.
    if trailing and not str(obj.get("message") or "").strip():
        obj["message"] = trailing
    obj.setdefault("facts", {})
    obj.setdefault("findings", [])
    obj.setdefault("message", "")
    obj.setdefault("stage", "interviewing")
    if not isinstance(obj["facts"], dict):
        obj["facts"] = {}
    if not isinstance(obj["findings"], list):
        obj["findings"] = []
    return obj


_MONEY = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(billion|million|thousand|bn|b|m|k)?\b",
    re.IGNORECASE)
_SCALE = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "m": 1e6,
          "thousand": 1e3, "k": 1e3}


def extract_money(text: str) -> list:
    out = []
    for num, unit in _MONEY.findall(text or ""):
        v = float(num.replace(",", ""))
        v *= _SCALE.get((unit or "").lower(), 1.0)
        out.append(v)
    return out


def unverified_figures(message: str, allowed: list) -> list:
    """Dollar amounts in `message` that match no computed number.

    Tolerance covers rounding a figure like $24,512,300 to "$24.5M" or "$25M".
    Small amounts under $1K are ignored as incidental.
    """
    bad = []
    for v in extract_money(message):
        if abs(v) < 1e3:
            continue
        ok = any(abs(v - a) <= max(0.06 * abs(a), 6e5) for a in allowed if a)
        if not ok:
            bad.append(_m(v))
    return bad


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------

@dataclass
class Session:
    id: str
    portco: dict
    comparison: dict
    facts: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    history: list = field(default_factory=list)
    trace: list = field(default_factory=list)
    # What the UI shows, one entry per message: role, content, the figure
    # check on agent replies, and when it was said. `history` above is what
    # the model sees; this is what a reopened diagnostic redisplays.
    transcript: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    # -- numbers the model is allowed to cite --------------------------------

    def allowed_numbers(self) -> list:
        """What the company spends, from its P&L, and what the user said.

        Peer dollar gaps and savings are deliberately absent: the diagnostic
        estimates neither, so a reply quoting one is caught by the guard.
        """
        nums = []
        c = self.comparison["company"]
        nums += [c.get("revenue"), c.get("ebitda")]
        for d in self.comparison["drivers"]:
            nums.append(d.get("company_dollars"))
        # Numbers the user volunteered are legitimate to repeat back.
        for v in self.facts.values():
            nums += extract_money(str(v))
        return [n for n in nums if n]

    # -- opportunities --------------------------------------------------------

    def record_opportunity(self, prop: dict) -> dict | None:
        """An action the model proposes, checked and stamped by code.

        No saving is estimated. Code refuses a cost area that must not be cut
        and attaches where the company ranks against peers today, so the rank
        shown is the data's, not the model's.
        """
        key = prop.get("driver")
        # R&D is the pipeline, EBITDA margin is the outcome, and SG&A would
        # repeat G&A.
        if key not in DRIVERS or key in ("rnd_pct", "ebitda_margin",
                                         "overhead_pct"):
            return None
        drv = next((d for d in self.comparison["drivers"]
                    if d["driver"] == key), None)
        lever = str(prop.get("lever", "")).strip()[:120]
        if drv is None or not lever:
            return None
        based_on = prop.get("based_on")
        based_on = ([str(b) for b in based_on][:6]
                    if isinstance(based_on, list) else [])
        spec = DRIVERS[key]
        opp = {
            "id": uuid.uuid4().hex[:8],
            "driver": key,
            "label": spec.label,
            "ebitda_role": spec.ebitda_role,
            "lever": lever,
            "rationale": str(prop.get("rationale", ""))[:400],
            "first_step": str(prop.get("first_step", ""))[:300],
            "based_on": based_on,
            # Recorded with no fact behind it: shown as not yet confirmed.
            "unsupported": not based_on,
        }
        if drv.get("available") and drv.get("percentile") is not None:
            opp["percentile_now"] = drv["percentile"]
        return opp

    def discard_last_user(self) -> None:
        """Undo the user message a failed turn appended.

        A turn that dies after the append leaves the question in history and
        the session answers it twice on the retry -- or, if the failure is
        deterministic, never answers again.
        """
        if self.history and self.history[-1]["role"] == "user":
            self.history.pop()

    def findings_totals(self) -> dict:
        # Kept as an object so the API and saved sessions keep one shape. With
        # no savings estimated, the count is all there is to total.
        return {"count": len(self.findings)}

    # -- prompting ------------------------------------------------------------

    def render_findings(self) -> str:
        if not self.findings:
            return "OPPORTUNITIES: none recorded yet."
        lines = ["OPPORTUNITIES recorded so far (no savings are estimated):"]
        for f in self.findings:
            rank = (f"; costlier than {f['percentile_now']:.0f}% of similar "
                    "companies" if "percentile_now" in f else "")
            tail = (" [UNSUPPORTED: no fact cited]" if f.get("unsupported")
                    else "")
            lines.append(
                f"- {f['lever']} ({f['label']}, "
                f"{ROLE_TEXT.get(f['ebitda_role'], f['ebitda_role'])}){rank}: "
                f"{f.get('rationale', '')}{tail}")
        return "\n".join(lines)

    def retrieved_context(self) -> str | None:
        """Document excerpts for whatever is being discussed right now.

        Retrieval is keyed on the latest user message so the excerpts track the
        conversation. On the opening turn there is no message yet, so the
        company's worst drivers stand in as the query -- those are what the
        agent is about to ask about.
        """
        query = next((h["content"] for h in reversed(self.history)
                      if h["role"] == "user"), "")
        if not query:
            # Lead with the drivers that carry the biggest gap: the opening
            # turn asks about them first, so those are the documents it needs.
            # Ordered by driver list alone, G&A came first and the facilities
            # register was never retrieved for a company whose gap was space.
            ranked = sorted(
                (d for d in self.comparison["drivers"]
                 if d.get("gap_to_median_usd") is not None),
                key=lambda d: d["gap_to_median_usd"], reverse=True)
            labels = [d["label"] for d in ranked[:3]] or [
                d["label"] for d in self.comparison["drivers"][:3]]
            query = (f"{', '.join(labels)}: sites, occupancy, leases, "
                     "headcount by function, duplicated teams, systems, "
                     "vendor contracts")
        try:
            return rag.render_context(self.portco["id"], query,
                                      top_k=config.RAG_TOP_K)
        except Exception:
            # Retrieval is an enrichment. If Pinecone is down or misconfigured
            # the diagnostic still runs on benchmarks alone.
            return None

    def build_prompt(self, extra: str = "") -> str:
        facts = (json.dumps(self.facts, indent=None) if self.facts
                 else "none yet")
        convo = "\n".join(
            f"{'USER' if h['role'] == 'user' else 'YOU'}: {h['content']}"
            for h in self.history[-16:])
        parts = [
            SYSTEM,
            "=" * 60,
            render_context(self.portco, self.comparison),
            "",
            f"FACTS the user has told you: {facts}",
            "",
            self.render_findings(),
        ]
        retrieved = self.retrieved_context()
        if retrieved:
            parts += ["", retrieved]
        parts += [
            "=" * 60,
            "CONVERSATION SO FAR:",
            convo or "(none - this is the opening turn)",
        ]
        if extra:
            parts += ["", extra]
        return "\n".join(parts)

    # -- the loop ---------------------------------------------------------------

    def _call(self, prompt: str, step: str) -> dict:
        res = llm.complete(prompt)
        entry = {"step": step, "model": res.model,
                 "duration_s": round(res.duration_s, 2),
                 "cost_usd": round(res.cost_usd, 4)}
        if res.permission_denials:
            entry["permission_denials"] = res.permission_denials
        try:
            action = parse_action(res.text)
        except (ValueError, json.JSONDecodeError) as e:
            entry["parse_error"] = str(e)
            self.trace.append(entry)
            raise llm.LLMError(f"could not parse model reply: {e}") from e
        self.trace.append(entry)
        return action

    def _stream_call(self, prompt: str, step: str):
        """Stream one model call, yielding ('delta', text) then ('action', obj).

        The JSON header is buffered whole before anything is emitted; only the
        prose after it can reach the user. Every figure the prose may quote
        exists before the call starts - nothing is computed afterwards - so
        the reply streams as it is written.
        """
        buf = ""
        prose_at = None      # index in buf where prose begins
        sent = 0             # chars of prose already emitted
        sent_any = False     # has any non-blank prose gone out yet
        usage = None

        for piece in llm.stream(prompt):
            if isinstance(piece, llm.StreamUsage):
                usage = piece
                break
            buf += piece
            if prose_at is None:
                lead = len(buf) - len(buf.lstrip())
                start, end = split_action(buf.lstrip())
                if start == -1 or end == -1:
                    continue
                prose_at = lead + end
            pending = buf[prose_at:]
            if not sent_any:
                # The blank line between the JSON and the prose is part of the
                # format, not the reply -- and so is a closing ``` left behind
                # by a fence that wrapped only the JSON. Both are held back
                # until real prose follows, so neither is ever emitted.
                cleaned = re.sub(r"^\s*```(?:json)?\s*", "", pending).lstrip()
                if not cleaned:
                    continue
                sent_any = True
                sent = len(pending) - len(cleaned)
            chunk = buf[prose_at + sent:]
            if chunk:
                sent += len(chunk)
                yield ("delta", chunk)

        entry = {"step": step,
                 "model": usage.model if usage else config.CLAUDE_CLI_MODEL,
                 "duration_s": round(usage.duration_s, 2) if usage else 0.0,
                 "cost_usd": round(usage.cost_usd, 4) if usage else 0.0}
        if usage:
            entry["input_tokens"] = usage.input_tokens
            entry["output_tokens"] = usage.output_tokens
        try:
            action = parse_action(buf)
        except (ValueError, json.JSONDecodeError) as e:
            entry["parse_error"] = str(e)
            self.trace.append(entry)
            raise llm.LLMError(f"could not parse model reply: {e}") from e
        self.trace.append(entry)
        yield ("action", action)

    def _absorb(self, action: dict) -> None:
        """Keep the facts and opportunities a model reply recorded."""
        for k, v in action["facts"].items():
            if k and v not in (None, ""):
                self.facts[str(k)[:60]] = v
        for prop in action["findings"]:
            opp = self.record_opportunity(prop)
            if opp:
                # Re-recording the same action replaces the earlier one.
                self.findings = [x for x in self.findings
                                 if not (x["driver"] == opp["driver"]
                                         and x["lever"] == opp["lever"])]
                self.findings.append(opp)

    def _payload(self, message: str, action: dict, bad: list,
                 turn_trace_start: int) -> dict:
        turn_trace = self.trace[turn_trace_start:]
        return {
            "session_id": self.id,
            "message": message,
            "stage": action.get("stage", "interviewing"),
            "facts": self.facts,
            "findings": self.findings,
            "findings_totals": self.findings_totals(),
            "guard": {"unverified_figures": bad, "checked": True},
            "trace": turn_trace,
            "turn_cost_usd": round(sum(t["cost_usd"] for t in turn_trace), 4),
        }

    def turn_stream(self, user_text: str | None):
        """One turn, as a stream of events for the UI.

        Event types: status (phase label), delta (prose to append), reset
        (discard what was streamed - the guard's rewrite replaces it), done
        (the same payload turn() returns), error.
        """
        turn_trace_start = len(self.trace)
        if user_text is not None:
            self.history.append({"role": "user", "content": user_text})

        opening = user_text is None
        yield {"type": "status",
               "text": "Reviewing peer benchmark data…" if opening
                       else "Working through your answer…"}

        action = None
        emitted = False
        for kind, payload in self._stream_call(
                self.build_prompt(OPENING if opening else ""), "respond"):
            if kind == "delta":
                emitted = True
                yield {"type": "delta", "text": payload}
            else:
                action = payload
        steps = 1
        self._absorb(action)

        if not emitted:
            # A reply in the older shape carries its prose inside the JSON, so
            # nothing streamed; send it in one piece.
            msg = action.get("message", "").strip()
            if msg:
                emitted = True
                yield {"type": "delta", "text": msg}

        message = action.get("message", "").strip()
        bad = unverified_figures(message, self.allowed_numbers())
        if bad and steps < config.MAX_AGENT_STEPS:
            if emitted:
                yield {"type": "reset"}
            yield {"type": "status", "text": "Checking the figures…"}
            retry = GUARD_RETRY.format(bad=", ".join(bad))
            for kind, payload in self._stream_call(
                    self.build_prompt(retry), "guard_retry"):
                if kind == "delta":
                    yield {"type": "delta", "text": payload}
                else:
                    action = payload
            steps += 1
            message = action.get("message", "").strip() or message
            bad = unverified_figures(message, self.allowed_numbers())

        self.history.append({"role": "assistant", "content": message})
        yield {"type": "done",
               "payload": self._payload(message, action, bad, turn_trace_start)}

    def turn(self, user_text: str | None) -> dict:
        """Run one agent turn. `user_text` None means the opening turn."""
        turn_trace_start = len(self.trace)
        if user_text is not None:
            self.history.append({"role": "user", "content": user_text})

        opening = user_text is None
        action = self._call(self.build_prompt(OPENING if opening else ""),
                            "respond")
        steps = 1
        self._absorb(action)

        message = action.get("message", "").strip()
        bad = unverified_figures(message, self.allowed_numbers())
        if bad and steps < config.MAX_AGENT_STEPS:
            retry = GUARD_RETRY.format(bad=", ".join(bad))
            action = self._call(self.build_prompt(retry), "guard_retry")
            steps += 1
            message = action.get("message", "").strip() or message
            bad = unverified_figures(message, self.allowed_numbers())

        self.history.append({"role": "assistant", "content": message})
        return self._payload(message, action, bad, turn_trace_start)


def start_session(portco: dict) -> tuple[Session, dict]:
    comparison = bm.compare_company(portco["financials"], portco["industry"],
                                    portco["fiscal_year"])
    s = Session(id=uuid.uuid4().hex, portco=portco, comparison=comparison)
    _SESSIONS[s.id] = s
    opening = s.turn(None)
    opening["comparison"] = comparison
    return s, opening


def start_session_stream(portco: dict):
    """Open a session and stream its opening turn.

    The comparison rides on the `done` event rather than being sent first: the
    client needs the session id and the benchmark together, and the id only
    exists once the session is made.
    """
    comparison = bm.compare_company(portco["financials"], portco["industry"],
                                    portco["fiscal_year"])
    s = Session(id=uuid.uuid4().hex, portco=portco, comparison=comparison)
    _SESSIONS[s.id] = s
    for ev in s.turn_stream(None):
        if ev.get("type") == "done":
            ev["payload"]["comparison"] = comparison
        yield ev


def get_session(session_id: str) -> Session | None:
    return _SESSIONS.get(session_id)


def restore_session(state: dict) -> Session:
    """Rebuild a saved session and make it live again, so it can continue.

    Unknown keys are dropped rather than rejected: a file saved by an older
    build must still open after a field is renamed or removed.
    """
    known = {f.name for f in fields(Session)}
    s = Session(**{k: v for k, v in state.items() if k in known})
    _SESSIONS[s.id] = s
    return s


def forget_session(session_id: str) -> None:
    _SESSIONS.pop(session_id, None)
