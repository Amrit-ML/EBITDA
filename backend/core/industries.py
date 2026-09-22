"""The two industries the engine benchmarks.

Membership comes from the Biotechnology and Pharmaceutical company lists
(data/industry_map.csv, built by build_industry_map.py), not from SIC codes:
SEC files clinical-stage biotechs and large pharma alike under SIC 2834.
"""

INDUSTRIES = {
    "biotech": {
        "label": "Biotechnology",
        "source_sector": "Drugs (Biotechnology)",
        "description": ("Biologics, gene and cell therapy, platform and "
                        "research-driven drug developers."),
    },
    "pharma": {
        "label": "Pharmaceutical",
        "source_sector": "Drugs (Pharmaceutical)",
        "description": ("Branded, specialty and generic drug manufacturers "
                        "and marketers."),
    },
}


def label_for(industry: str) -> str:
    return INDUSTRIES.get(industry, {}).get("label", industry)


def is_valid(industry: str) -> bool:
    return industry in INDUSTRIES
