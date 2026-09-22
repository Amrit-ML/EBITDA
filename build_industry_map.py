import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SECTORS = {
    "Drugs (Biotechnology)": "biotech",
    "Drugs (Pharmaceutical)": "pharma",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--panel", type=Path,
                    default=HERE.parent / "data" / "panel_wide.csv")
    ap.add_argument("--out", type=Path, default=HERE / "data" / "industry_map.csv")
    args = ap.parse_args()

    if not args.panel.exists():
        sys.exit(f"{args.panel} not found. Run fetch_edgar.py and build_panel.py "
                 f"in C:\\projects-local\\data first.")

    df = pd.read_csv(args.panel, low_memory=False,
                     usecols=["cik", "Ticker", "Company Name", "Sector"])
    unknown = set(df["Sector"].dropna()) - set(SECTORS)
    if unknown:
        sys.exit(f"Unexpected sectors in {args.panel.name}: {sorted(unknown)}")

    m = (df.dropna(subset=["cik", "Sector"])
         .drop_duplicates("cik")
         .assign(cik=lambda d: d["cik"].astype(int),
                 industry=lambda d: d["Sector"].map(SECTORS))
         .rename(columns={"Ticker": "ticker", "Company Name": "company",
                          "Sector": "source_sector"})
         [["cik", "industry", "source_sector", "ticker", "company"]]
         .sort_values(["industry", "cik"]))

    clash = df.dropna(subset=["cik"]).groupby("cik")["Sector"].nunique()
    if (clash > 1).any():
        sys.exit(f"{int((clash > 1).sum())} CIKs appear in both lists.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    m.to_csv(args.out, index=False, encoding="utf-8")
    print(f"wrote {args.out}: {len(m)} filers "
          f"{m['industry'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
