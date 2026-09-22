"""
fetch_frames.py

Downloads cost-structure benchmark data for EVERY US SEC filer, across all
industries, from the EDGAR XBRL `frames` API.

WHY FRAMES AND NOT companyfacts
-------------------------------
A per-company approach (one companyfacts call each) costs ~5,000 requests and
roughly 10 GB for a multi-industry universe. The frames endpoint inverts the
axis: one request returns a single concept for every filer that reported it in
a given period. ~16 concepts x 7 years is ~112 requests and a few hundred MB.

For a single industry, per-company is fine. For "all of them", frames is the
only sane route.

SIC CODES
---------
frames does not carry SIC, so industry comes from the DERA Financial Statement
Data Sets: each quarterly ZIP has a sub.txt with cik, name and sic. Two or
three quarters cover essentially every active filer.

SETUP
-----
    pip install requests pandas

USAGE
-----
    python fetch_frames.py --years 2019 2025 --out data/frames_panel.csv
    python build_sic_map.py          # run first; writes data/sic_map.csv

NOTES
-----
- SEC asks for a real contact email in the User-Agent. Pass --email.
- Rate limit is 10 req/s; this stays near 8/s.
- RESUMABLE: each (concept, year) is appended as it completes and skipped on
  re-run, so a dropped connection costs one request rather than the run.
- EBITDA is not a GAAP tag. It is derived downstream as operating income plus
  D&A; both are well covered (5,012 and 3,036 filers for CY2024).
"""

import argparse
import csv
import os
import sys
import time

import requests

FRAMES = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/CY{year}.json"

# Concept -> (metric, priority). Several tags can feed one metric; priority
# resolves collisions downstream, lowest number winning.
#
# Coverage measured on CY2024 (filers reporting):
#   OperatingIncomeLoss 5012 | ShareBasedCompensation 4569 | CAPEX 3944
#   OperatingLeaseCost 3397 | G&A 3372 | D&A 3036 | SG&A 1971
#   AdvertisingExpense 1630 | ProfessionalFees 1037 | LaborAndRelated 920
# Technology spend (279) and headcount (unpublished) are NOT obtainable here --
# the agent asks the user for those instead.
CONCEPTS = {
    # --- top line ---
    "Revenues": ("revenue", 3),
    "RevenueFromContractWithCustomerExcludingAssessedTax": ("revenue", 1),
    "RevenueFromContractWithCustomerIncludingAssessedTax": ("revenue", 2),
    "SalesRevenueNet": ("revenue", 4),
    # --- earnings, for EBIT/EBITDA ---
    "OperatingIncomeLoss": ("operating_income", 1),
    "NetIncomeLoss": ("net_income", 1),
    "DepreciationDepletionAndAmortization": ("depreciation_amortization", 1),
    "DepreciationAmortizationAndAccretionNet": ("depreciation_amortization", 2),
    "DepreciationAndAmortization": ("depreciation_amortization", 3),
    # --- cost of delivery ---
    "CostOfRevenue": ("cost_of_revenue", 1),
    "CostOfGoodsAndServicesSold": ("cost_of_revenue", 2),
    # --- the cost drivers ---
    "SellingGeneralAndAdministrativeExpense": ("sga", 1),
    "GeneralAndAdministrativeExpense": ("ga", 1),
    "SellingAndMarketingExpense": ("sales_marketing", 1),
    "ResearchAndDevelopmentExpense": ("rnd", 1),
    "OperatingLeaseCost": ("facilities", 1),
    "AdvertisingExpense": ("advertising", 1),
    "ProfessionalFees": ("professional_fees", 1),
    "LaborAndRelatedExpense": ("labor", 1),
    "ShareBasedCompensation": ("share_based_comp", 1),
    "PaymentsToAcquirePropertyPlantAndEquipment": ("capex", 1),
    # --- scale ---
    "Assets": ("assets", 1),
}

FIELDNAMES = ["cik", "entity_name", "fy", "metric", "concept", "priority",
              "value", "unit"]


class Client:
    def __init__(self, email, min_interval=0.13):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": f"ebitda-benchmark-hackathon {email}",
            "Accept-Encoding": "gzip, deflate",
        })
        self.min_interval = min_interval
        self._last = 0.0
        self.bytes = 0

    def get(self, url, tries=6, timeout=120):
        """Returns a Response, or None. Never raises: a transient DNS blip must
        not abort a long run."""
        for attempt in range(tries):
            gap = self.min_interval - (time.time() - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.time()
            try:
                r = self.s.get(url, timeout=timeout)
            except requests.RequestException as e:
                if attempt == tries - 1:
                    print(f"    network error, giving up: {type(e).__name__}",
                          flush=True)
                    return None
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            if r.status_code == 200:
                self.bytes += len(r.content)
                return r
            if r.status_code == 404:
                return None  # concept not published for this period
            if attempt == tries - 1:
                return None
            time.sleep(2 ** attempt + 0.5)
        return None


def load_done(path):
    """(concept, fy) pairs already written, for resume."""
    done = set()
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return done
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add((row["concept"], int(row["fy"])))
    return done


def main():
    ap = argparse.ArgumentParser(
        description="Download cross-industry cost benchmarks from EDGAR frames.")
    ap.add_argument("--years", nargs=2, type=int, default=[2019, 2025],
                    metavar=("FROM", "TO"))
    ap.add_argument("--out", default="data/frames_panel.csv")
    ap.add_argument("--email", default="research-contact@example.com")
    args = ap.parse_args()

    if "example.com" in args.email:
        print("NOTE: placeholder contact email. Pass --email you@domain to "
              "identify yourself to SEC as they request.\n")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    years = list(range(args.years[0], args.years[1] + 1))
    client = Client(args.email)

    done = load_done(args.out)
    if done:
        print(f"Resuming: {len(done)} (concept, year) pairs already fetched.\n")

    tasks = [(c, y) for c in CONCEPTS for y in years]
    todo = [t for t in tasks if t not in done]
    print(f"{len(CONCEPTS)} concepts x {len(years)} years = {len(tasks)} "
          f"requests; {len(todo)} to fetch.\n")

    write_header = not os.path.exists(args.out) or os.path.getsize(args.out) == 0
    rows_total = 0
    missing = []

    with open(args.out, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if write_header:
            w.writeheader()

        for i, (concept, year) in enumerate(todo, 1):
            metric, priority = CONCEPTS[concept]
            r = client.get(FRAMES.format(concept=concept, year=year))
            if r is None:
                missing.append((concept, year))
                print(f"[{i}/{len(todo)}] {concept[:44]:46s} CY{year}  -- none",
                      flush=True)
                continue
            try:
                data = r.json().get("data", [])
            except ValueError:
                missing.append((concept, year))
                continue

            for e in data:
                w.writerow({
                    "cik": e.get("cik"),
                    "entity_name": e.get("entityName"),
                    "fy": year,
                    "metric": metric,
                    "concept": concept,
                    "priority": priority,
                    "value": e.get("val"),
                    "unit": "USD",
                })
            f.flush()
            rows_total += len(data)
            print(f"[{i}/{len(todo)}] {concept[:44]:46s} CY{year}  "
                  f"{len(data):5d} filers  [{client.bytes/1e6:.0f} MB]",
                  flush=True)

    print(f"\nDone -> {args.out}")
    print(f"  rows written this run : {rows_total:,}")
    print(f"  downloaded            : {client.bytes/1e6:.0f} MB")
    if missing:
        print(f"  no data for {len(missing)} (concept, year) pairs "
              f"(normal: not every tag is published every year)")


if __name__ == "__main__":
    main()
