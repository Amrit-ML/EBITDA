"""Synthetic sample P&Ls for the demo, one per industry.

SYNTHETIC. These are invented businesses, not real filers. Hackathon rules call
for synthetic client data; the benchmarks they are compared against are real.
They have no company names: the UI calls them by their tagline, and the model
is never given a name.

Each has cost problems PLANTED relative to actual peer distributions measured
from the benchmark panel (peers FY2023-25, revenue $250M-1B):

  Pharmaceutical (22 filers in the band):
    G&A median 14.2% / p75 17.4%     facilities median 0.7% / p75 1.8%
    EBITDA margin median 11.7% / p75 20.4%
  Biotechnology (32 filers in the band):
    G&A median 28.3% / p75 37.6%     facilities median 1.3% / p75 2.3%
    R&D median 28.1% / p75 71.6%     EBITDA margin median 1.5% / p75 15.6%

`financials` is what the company would hand over. `hidden_facts` is what only an
interview reveals -- headcount, org structure, sites -- which the benchmark data
cannot see. The agent is not given hidden_facts; they exist so the demo operator
can answer its questions consistently, and so tests can check the agent asks.
"""

PORTCOS = {
    "pharma-sample": {
        "id": "pharma-sample",
        "name": "Sample specialty pharma",
        "tagline": "Specialty pharma, PE-backed roll-up",
        "industry": "pharma",
        "fiscal_year": 2025,
        "synthetic": True,
        "financials": {
            "revenue": 480_000_000,
            "cost_of_revenue": 216_000_000,
            "ga": 96_000_000,               # 20.0% -- planted, above p75 17.4%
            "sales_marketing": 67_200_000,  # 14.0% -- one field force, fine
            "overhead": 163_200_000,        # 34.0% SG&A, below median
            "rnd": 43_200_000,              # 9.0% -- below median, protect
            "facilities": 10_080_000,       # 2.1% -- planted, above p75 1.8%
            "advertising": 26_400_000,      # 5.5% -- at median (DTC brands)
            "capex": 4_800_000,             # 1.0%
            "depreciation_amortization": 14_400_000,
            "operating_income": 57_600_000,
            "ebitda": 72_000_000,           # 15.0% -- above median, below p75
            "professional_fees": 11_500_000,
        },
        "planted": {
            "ga_pct": "Three acquired companies each kept their own finance, "
                      "HR, regulatory affairs and IT.",
            "facilities_pct": "Two legacy offices below 40% occupancy.",
        },
        "hidden_facts": {
            "total_headcount": 1150,
            "ga_headcount": 260,
            "acquisitions": "3 bolt-on acquisitions since 2021, each kept its "
                            "own finance, HR, regulatory affairs and IT",
            "erp_instances": 3,
            "sites": "5: plants in Puerto Rico and North Carolina, offices in "
                     "New Jersey, Ohio and Florida; New Jersey and Ohio below "
                     "40% occupancy",
            "field_force": "One 140-rep field force across three brands",
            "growth_plan": "Two late-stage pipeline assets; sponsor targets a "
                           "2028 exit",
        },
    },
    "biotech-sample": {
        "id": "biotech-sample",
        "name": "Sample commercial-stage biotech",
        "tagline": "Commercial-stage biotech, post-merger",
        "industry": "biotech",
        "fiscal_year": 2025,
        "synthetic": True,
        "financials": {
            "revenue": 520_000_000,
            "cost_of_revenue": 72_800_000,
            "ga": 208_000_000,              # 40.0% -- planted, above p75 37.6%
            "sales_marketing": 156_000_000, # 30.0% -- below median, fine
            "overhead": 364_000_000,        # 70.0% SG&A
            "rnd": 182_000_000,             # 35.0% -- above median: PROTECT
            "facilities": 14_560_000,       # 2.8% -- planted, above p75 2.3%
            "advertising": 11_440_000,      # 2.2% -- near median
            "capex": 10_400_000,            # 2.0% -- at median
            "depreciation_amortization": 13_000_000,
            "operating_income": -98_800_000,
            "ebitda": -85_800_000,          # -16.5% -- below median 1.5%
            "professional_fees": 24_000_000,
        },
        # R&D sits above the median on purpose. It is the value driver of a
        # biotech with Phase 3 readouts ahead, so the demo can show the agent
        # refusing to cut it even though it is the largest cost line.
        "planted": {
            "ga_pct": "US and EU headquarters since the 2022 merger, each with "
                      "its own finance, HR, legal and IT.",
            "facilities_pct": "San Diego lab ~40% utilised since a program "
                              "was discontinued.",
        },
        "hidden_facts": {
            "total_headcount": 1400,
            "ga_headcount": 390,
            "corporate_structure": "US (Cambridge) and EU (Basel) headquarters "
                                   "since the 2022 merger, each with its own "
                                   "finance, HR, legal and IT",
            "erp_instances": 2,
            "sites": "4 lab and office sites; San Diego lab ~40% utilised since "
                     "the oncology program was discontinued",
            "pipeline": "3 Phase 3 readouts in 2026-27; R&D is the value driver",
            "growth_plan": "Targeting EBITDA breakeven by 2027 without slowing "
                           "the pipeline",
        },
    },
}


def list_portcos() -> list:
    return [
        {k: p[k] for k in ("id", "name", "tagline", "industry", "fiscal_year",
                           "synthetic")}
        for p in PORTCOS.values()
    ]
