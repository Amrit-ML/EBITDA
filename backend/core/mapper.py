"""Model-assisted line-item mapping, used only when the synonym list fails.

Real exports say "Total net revenues from collaborations", "Cost of sales -
products", "G&A (incl. share-based comp)". A fixed synonym list cannot cover
that, and making the user map fourteen fields by hand is not "upload your P&L".

The division of labour is the same as everywhere else in this engine: the model
supplies JUDGMENT (which printed label means which field), code supplies
ARITHMETIC (reading the cells, scaling units, computing every benchmark). The
model sees labels and one sample value per label -- never the whole file -- and
may only choose from labels that exist, checked on the way back.
"""

import json
import re
from typing import Optional

import config
from core import llm

PROMPT = """You map the line items of a company's profit & loss export onto a \
fixed set of fields.

LABELS FROM THE FILE (choose only from these, copied exactly):
{labels}

FIELDS TO FILL:
{fields}

RULES
- Only map a label when it clearly IS that field. Omit anything you are unsure \
of; a wrong mapping produces a wrong benchmark, an omission does not.
- revenue means TOTAL revenue. Never map a single component (one product, one \
region, collaboration or royalty revenue alone) unless it is the only revenue \
line in the file.
- cost_of_revenue is cost of sales/COGS, never total costs or operating expenses.
- overhead is SG&A as a single combined line. If G&A and sales & marketing are \
listed separately, map those two and leave overhead empty.
- Subtotals such as gross profit, total operating expenses, income before tax, \
and any balance-sheet or cash-flow line are not fields here: omit them.
- Ignore units, signs and magnitudes entirely; code handles those.

Return ONLY this JSON, no prose, no code fences:
{{"mapping": {{"field_key": "label exactly as given"}}}}"""


def _parse(text: str) -> dict:
    fenced = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    start, end = fenced.find("{"), fenced.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in reply")
    data = json.loads(fenced[start:end + 1])
    mapping = data.get("mapping", data)
    return mapping if isinstance(mapping, dict) else {}


def suggest(labels: list, fields: dict, samples: Optional[dict] = None,
            model: Optional[str] = None) -> dict:
    """{field: label} for labels the model recognises. Never raises.

    Returns {} on any failure -- a missing AI suggestion leaves the user with
    the manual mapping table, which is the status quo, not a broken upload.
    """
    labels = [str(l).strip() for l in labels if str(l).strip()]
    if not labels or not fields:
        return {}

    samples = samples or {}
    shown = "\n".join(
        f"- {l}" + (f"   (e.g. {samples[l]})" if samples.get(l) else "")
        for l in labels[:120])
    wanted = "\n".join(f"- {key}: {label}" for key, label in fields.items())

    try:
        result = llm.complete(PROMPT.format(labels=shown, fields=wanted),
                              model=model or config.CLAUDE_CLI_MODEL)
        proposed = _parse(result.text)
    except Exception:
        return {}

    # The model may only point at labels that exist and fields we asked for.
    allowed = {l.lower(): l for l in labels}
    out = {}
    for field, label in proposed.items():
        if field not in fields or not isinstance(label, str):
            continue
        real = allowed.get(label.strip().lower())
        if real:
            out[field] = real
    return out
