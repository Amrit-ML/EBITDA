"""
build_sic_map.py

Builds a CIK -> (name, SIC, industry) map from the DERA Financial Statement
Data Sets, since the EDGAR frames API carries no industry classification.

Each quarterly ZIP's sub.txt lists every submission with its filer's SIC. Three
recent quarters cover essentially every active filer (2025q1 alone yields 5,672
distinct CIKs across 390 SIC codes, because most calendar-year 10-Ks land in Q1).

USAGE
-----
    python build_sic_map.py --zips data/2024q3.zip data/2024q4.zip data/2025q1.zip
"""

import argparse
import csv
import io
import zipfile

# SIC major groups (first two digits) -> a readable sector. Finer industry
# labels come from the 4-digit SIC; this rollup exists so thin 4-digit cells
# have a sensible level to widen to.
SIC_DIVISIONS = [
    (100, 999, "Agriculture, Forestry & Fishing"),
    (1000, 1499, "Mining"),
    (1500, 1799, "Construction"),
    (2000, 3999, "Manufacturing"),
    (4000, 4999, "Transportation, Communications & Utilities"),
    (5000, 5199, "Wholesale Trade"),
    (5200, 5999, "Retail Trade"),
    (6000, 6799, "Finance, Insurance & Real Estate"),
    (7000, 8999, "Services"),
    (9100, 9729, "Public Administration"),
    (9900, 9999, "Nonclassifiable"),
]

# Common, recognisable 2-digit major groups, used for the industry picker.
MAJOR_GROUPS = {
    "13": "Oil & Gas Extraction",
    "20": "Food & Kindred Products",
    "28": "Chemicals & Pharmaceuticals",
    "35": "Industrial Machinery & Computer Equipment",
    "36": "Electronic & Electrical Equipment",
    "37": "Transportation Equipment",
    "38": "Instruments & Medical Devices",
    "48": "Communications",
    "49": "Electric, Gas & Sanitary Services",
    "50": "Wholesale — Durable Goods",
    "58": "Eating & Drinking Places",
    "59": "Miscellaneous Retail",
    "60": "Depository Institutions",
    "63": "Insurance Carriers",
    "67": "Holding & Investment Offices",
    "73": "Business Services & Software",
    "80": "Health Services",
    "87": "Engineering, Accounting & Management Services",
}


def division_for(sic: int) -> str:
    for lo, hi, label in SIC_DIVISIONS:
        if lo <= sic <= hi:
            return label
    return "Unknown"


def main():
    ap = argparse.ArgumentParser(description="Build CIK -> SIC map.")
    ap.add_argument("--zips", nargs="+", required=True)
    ap.add_argument("--out", default="data/sic_map.csv")
    args = ap.parse_args()

    # Later quarters overwrite earlier ones, so a company that changed SIC or
    # name is recorded as of its most recent filing.
    best = {}
    for path in sorted(args.zips):
        z = zipfile.ZipFile(path)
        with z.open("sub.txt") as f:
            rdr = csv.DictReader(
                io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                delimiter="\t")
            n = 0
            for r in rdr:
                sic = (r.get("sic") or "").strip()
                if not sic or not sic.isdigit() or int(sic) == 0:
                    continue
                best[int(r["cik"])] = {
                    "cik": int(r["cik"]),
                    "name": r["name"].strip(),
                    "sic": int(sic),
                    "state": (r.get("stprba") or "").strip(),
                }
                n += 1
        print(f"  {path}: {n} submissions with SIC")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "cik", "name", "sic", "sic2", "major_group", "division", "state"])
        w.writeheader()
        for rec in best.values():
            sic2 = f"{rec['sic']:04d}"[:2]
            w.writerow({
                **rec,
                "sic2": sic2,
                "major_group": MAJOR_GROUPS.get(sic2, ""),
                "division": division_for(rec["sic"]),
            })

    divisions = {}
    for rec in best.values():
        d = division_for(rec["sic"])
        divisions[d] = divisions.get(d, 0) + 1

    print(f"\nwrote {len(best):,} filers -> {args.out}")
    print(f"distinct SIC codes: {len({r['sic'] for r in best.values()})}")
    print("\nfilers by division:")
    for d, n in sorted(divisions.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {d}")


if __name__ == "__main__":
    main()
