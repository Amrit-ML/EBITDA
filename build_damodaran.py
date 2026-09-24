"""
build_damodaran.py

Pulls the Biotechnology and Pharmaceutical rows from Aswath Damodaran's US
"Operating and Net Margins by Industry" table (NYU Stern), which the Insights
page uses as its peer benchmark for the SG&A ratios.

The table is aggregate: each margin is the industry's summed numerator over
its summed revenue, so large companies weigh more than small ones. Damodaran
updates it once a year, in January.

USAGE
-----
    python build_damodaran.py
"""

import argparse
import io
import re
import sys
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/margin.html"

# Damodaran's industry name -> the engine's industry key.
SECTORS = {
    "Drugs (Biotechnology)": "biotech",
    "Drugs (Pharmaceutical)": "pharma",
}

# Damodaran's column heading -> our column. Headings are matched with runs of
# whitespace collapsed, since the page wraps them across lines.
COLUMNS = {
    "Number of firms": "firms",
    "Gross Margin": "gross_margin",
    "Net Margin": "net_margin",
    "Pre-tax Unadjusted Operating Margin": "operating_margin",
    "EBITDA/Sales": "ebitda_margin",
    "R&D/Sales": "rnd_pct_revenue",
    "SG&A/ Sales": "sga_pct_revenue",
    "Stock-Based Compensation/Sales": "share_based_comp_pct_revenue",
}


def squash(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--out", type=Path, default=HERE / "data" / "damodaran_margins.csv")
    args = ap.parse_args()

    req = urllib.request.Request(args.url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")

    m = re.search(r"dated in\s+([A-Z][a-z]+\s+\d{4})", html)
    as_of = m.group(1) if m else ""

    # The first row of the table holds the real headings.
    raw = pd.read_html(io.StringIO(html), header=None)[0]
    raw.columns = [squash(c) for c in raw.iloc[1]]
    raw = raw.iloc[2:]
    raw["Industry Name"] = raw["Industry Name"].map(squash)

    missing = [c for c in COLUMNS if squash(c) not in raw.columns]
    if missing:
        sys.exit(f"Headings not found on the page (layout changed?): {missing}")

    rows = raw[raw["Industry Name"].isin(SECTORS)]
    if len(rows) != len(SECTORS):
        sys.exit(f"Expected {sorted(SECTORS)}, found {sorted(rows['Industry Name'])}")

    out = pd.DataFrame({"industry": rows["Industry Name"].map(SECTORS),
                        "source_industry": rows["Industry Name"]})
    for heading, col in COLUMNS.items():
        v = rows[squash(heading)].astype(str).str.replace("%", "").str.replace(",", "")
        v = pd.to_numeric(v, errors="coerce")
        out[col] = v if col == "firms" else (v / 100).round(6)
    out["as_of"] = as_of
    out["source_url"] = args.url

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False, encoding="utf-8")
    print(f"wrote {args.out} ({as_of or 'date not found'})")
    print(out.drop(columns=["source_url"]).to_string(index=False))


if __name__ == "__main__":
    main()
