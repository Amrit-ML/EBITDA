"""Cost-driver registry.

Single source of truth for what can be benchmarked, how it is labelled, what
counts as a plausible value, which direction is "better", and how each driver
may be combined into a total.

That last part is where naive tools go wrong. The drivers overlap:

- SG&A *contains* G&A, so their gaps cannot be added.
- Operating lease cost is allocated across G&A and cost of revenue, so a
  facilities gap may partly duplicate a G&A gap.
- CAPEX is not an EBITDA item at all. Cutting it improves free cash flow, not
  EBITDA, and adding it to an EBITDA total overstates the prize.

`ebitda_role` makes those rules explicit so the total is built in code rather
than by a model adding numbers up.
"""

from dataclasses import asdict, dataclass

# How a driver may contribute to a total EBITDA opportunity.
LEVER = "lever"                  # independent EBITDA lever, safe to sum
LEVER_OVERLAP = "lever_overlap"  # EBITDA lever that may duplicate another
ROLLUP = "rollup"                # contains other drivers; never summed
CASH = "cash"                    # free-cash-flow lever, not EBITDA
GROWTH = "growth"                # benchmarked, never recommended as a cut
OUTCOME = "outcome"              # the result, not a lever


@dataclass(frozen=True)
class Driver:
    key: str
    label: str
    source: str
    clip_low: float
    clip_high: float
    lower_is_better: bool
    ebitda_role: str
    description: str

    def as_dict(self):
        return asdict(self)


DRIVERS = {d.key: d for d in [
    Driver("ga_pct", "G&A", "ga", 0.0, 1.0, True, LEVER,
           "General & administrative: finance, HR, legal, executive and IT "
           "overhead. The usual home of duplicated regional functions."),
    Driver("advertising_pct", "Advertising", "advertising", 0.0, 0.6, True,
           LEVER,
           "Advertising expense, the most discretionary cost line. Sits in "
           "selling expense, so it does not overlap G&A."),
    Driver("facilities_pct", "Facilities", "facilities", 0.0, 0.5, True,
           LEVER_OVERLAP,
           "Operating lease cost for offices, plants and warehouses. Lease "
           "cost is allocated into both G&A and cost of revenue, so this gap "
           "can partly duplicate the G&A gap."),
    Driver("overhead_pct", "SG&A (total overhead)", "overhead", 0.0, 1.5,
           True, ROLLUP,
           "Selling, general & administrative combined. Contains G&A, so it "
           "gives context but is never added to the G&A opportunity."),
    Driver("capex_pct", "CAPEX", "capex", 0.0, 1.0, True, CASH,
           "Purchases of property, plant & equipment. Reducing it improves "
           "free cash flow, not EBITDA."),
    Driver("sales_marketing_pct", "Sales & marketing", "sales_marketing",
           0.0, 1.0, True, GROWTH,
           "Selling and marketing. Growth-linked: reviewed for duplication "
           "such as overlapping regional teams, never sized as a blunt cut."),
    Driver("rnd_pct", "R&D", "rnd", 0.0, 2.0, True, GROWTH,
           "Research & development. Protected growth investment."),
    Driver("ebitda_margin", "EBITDA margin", "ebitda", -1.0, 0.8, False,
           OUTCOME,
           "Operating income plus depreciation & amortisation, over revenue."),
]}

# Too thin to benchmark in most cells (professional fees: 1 filer in the
# industrial machinery 250M-1B cell; labor: 1). The agent may use these as the
# company's own context, never as a peer comparison.
UNBENCHMARKABLE = {
    "professional_fees": "Professional & vendor fees",
    "labor": "Labor & related",
    "headcount": "Headcount",
    "tech_spend": "Technology & software spend",
}
