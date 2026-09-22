"""Upload parsing tests.

Each trap here produces a confident wrong benchmark if it regresses: wrong
orientation, units read as dollars, negative expenses, or a synonym grabbing
the wrong line.
"""

from pathlib import Path

import pandas as pd
import pytest

from core import benchmarks as bm
from core import companies, ingest

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def parse(name):
    return ingest.parse_upload((SAMPLES / name).read_bytes(), name)


def mapping_of(preview):
    return {f: s["label"] for f, s in preview["suggested_mapping"].items()}


# --- the two sample layouts agree ------------------------------------------

@pytest.fixture(scope="module")
def both():
    rows = parse("pharma_pl_line_items_thousands.csv")
    cols = parse("pharma_pl_columns_dollars.csv")
    e_rows = ingest.extract(rows["upload_id"], mapping_of(rows),
                            rows["default_period"], "thousands")
    e_cols = ingest.extract(cols["upload_id"], mapping_of(cols),
                            cols["default_period"], "dollars")
    return rows, cols, e_rows, e_cols


def test_orientation_detected(both):
    rows, cols, _, _ = both
    assert rows["orientation"] == "rows"
    assert cols["orientation"] == "columns"


def test_orientation_falls_back_to_period_position_when_no_synonyms_match():
    """When labels are too unusual for the synonym list to recognise either
    axis, the row-vs-column comparison is 0-to-0, and defaulting to "columns"
    is a coin flip that is wrong most of the time. The periods (years) almost
    always run across the header row, so that is the tiebreaker: a genuinely
    novel rows-layout file must still be read as rows, so an AI-assisted
    mapper (which relies on orientation being right first) gets a fair shot
    instead of a corrupted table.
    """
    csv = (b"Item,FY2024\n"
           b"Topline,480000000\n"
           b"Direct cost outlay,216000000\n"
           b"Corporate overhead,96000000\n")
    p = ingest.parse_upload(csv, "novel_labels.csv")
    assert p["orientation"] == "rows"
    assert p["labels"] == ["Topline", "Direct cost outlay", "Corporate overhead"]
    assert p["periods"] == [{"key": "FY2024", "label": "FY2024", "year": 2024}]


def test_units_detected_from_title(both):
    rows, cols, _, _ = both
    assert rows["detected_units"] == "thousands"
    assert cols["detected_units"] is None


def test_default_period_is_latest_year(both):
    rows, cols, _, _ = both
    assert rows["default_period"] == "FY2024"
    assert next(p for p in cols["periods"]
                if p["key"] == cols["default_period"])["year"] == 2024


def test_both_layouts_yield_identical_financials(both):
    _, _, e_rows, e_cols = both
    a, b = e_rows["financials"], e_cols["financials"]
    assert set(a) == set(b)
    for k in a:
        assert a[k] == pytest.approx(b[k]), k
    assert a["revenue"] == pytest.approx(310_000_000)


def test_bracketed_expenses_normalised_positive(both):
    _, _, e_rows, _ = both
    f = e_rows["financials"]
    for k in ("cost_of_revenue", "ga", "sales_marketing", "rnd", "capex"):
        assert f[k] > 0, k


def test_memo_lines_flagged_as_guesses(both):
    rows, _, _, _ = both
    assert rows["suggested_mapping"]["facilities"]["confidence"] == "partial"
    assert rows["suggested_mapping"]["revenue"]["confidence"] == "exact"


# --- synonym traps ------------------------------------------------------------

def test_rent_does_not_match_current_assets():
    m = ingest.suggest_mapping(["Total current assets", "Rent"])
    assert m["facilities"]["label"] == "Rent"


def test_sales_does_not_steal_sales_and_marketing_or_cost_of_sales():
    m = ingest.suggest_mapping(["Net Sales", "Cost of Sales", "Sales & Marketing"])
    assert m["revenue"]["label"] == "Net Sales"
    assert m["cost_of_revenue"]["label"] == "Cost of Sales"
    assert m["sales_marketing"]["label"] == "Sales & Marketing"


def test_drug_company_revenue_wording():
    """Total revenue, not one component of it, when both are present."""
    m = ingest.suggest_mapping(["Net product revenue", "Collaboration revenue",
                                "Cost of product sales"])
    assert m["revenue"] == {"label": "Net product revenue", "confidence": "exact"}
    assert m["cost_of_revenue"]["label"] == "Cost of product sales"
    m = ingest.suggest_mapping(["Collaboration revenue", "Royalty revenue", "Total revenues"])
    assert m["revenue"]["label"] == "Total revenues"


def test_ebitda_not_taken_as_ebit():
    m = ingest.suggest_mapping(["EBIT", "EBITDA"])
    assert m["operating_income"]["label"] == "EBIT"
    assert m["ebitda"]["label"] == "EBITDA"


def test_plain_numbers_are_not_a_units_hint():
    """'420,000' normalises to '420 000'; that must not mean 'thousands'."""
    assert ingest.detect_units(["Revenue", "420,000", "1,000"]) is None
    assert ingest.detect_units(["Income statement ($000s)"]) == "thousands"
    assert ingest.detect_units(["USD in millions"]) == "millions"


@pytest.mark.parametrize("raw,expected", [
    ("1,234", 1234.0), ("(1,234)", -1234.0), ("$2.5M", 2.5e6), ("450k", 450e3),
    ("—", None), ("n/a", None), ("", None), (12, 12.0),
])
def test_to_number(raw, expected):
    assert ingest.to_number(raw) == (pytest.approx(expected)
                                     if expected is not None else None)


# --- company creation ---------------------------------------------------------

def test_derivations_match_peer_logic():
    f = companies.normalise_financials({
        "revenue": 100.0, "ga": 10.0, "sales_marketing": 5.0,
        "operating_income": 8.0, "depreciation_amortization": 2.0})
    assert f["overhead"] == 15.0
    assert f["ebitda"] == 10.0


def test_ebitda_not_assumed_equal_to_ebit_without_da():
    f = companies.normalise_financials({"revenue": 100.0, "operating_income": 8.0})
    assert "ebitda" not in f


def test_revenue_required():
    with pytest.raises(ValueError):
        companies.create_uploaded(None, "pharma", 2024, {"ga": 5.0})


def test_uploaded_pl_is_benchmarked_within_its_industry(both):
    _, _, e_rows, _ = both
    c = companies.create_uploaded(None, "pharma", 2024, e_rows["financials"], "t")
    assert c["name"] == "Your company"
    r = bm.compare_company(c["financials"], c["industry"], c["fiscal_year"])
    ga = next(d for d in r["drivers"] if d["driver"] == "ga_pct")
    assert ga["industry_level"] in ("industry", "drugs")
    assert r["company"]["industry_label"] == "Pharmaceutical"


def test_upload_outside_the_two_industries_rejected(both):
    _, _, e_rows, _ = both
    with pytest.raises(ValueError):
        companies.create_uploaded(None, "35", 2024, e_rows["financials"], "t")


def test_unknown_upload_id():
    with pytest.raises(ValueError):
        ingest.extract("nope", {"revenue": "Revenue"}, "0")


def test_rejects_single_column_file():
    with pytest.raises(ValueError):
        ingest.parse_upload(b"just one column\n1\n2\n", "x.csv")

# --- what can and cannot be read ----------------------------------------------
# A misread digit from a PDF or a screenshot becomes a confident wrong
# benchmark, so those are refused with instructions instead of guessed at.

@pytest.mark.parametrize("name,word", [
    ("deck.ppt", "PowerPoint 97-2003"), ("scan.png", "image"),
    ("photo.jpeg", "image"), ("memo.docx", "Word"), ("pack.zip", "archive"),
])
def test_unreadable_formats_are_refused_with_guidance(name, word):
    with pytest.raises(ValueError) as e:
        ingest.parse_upload(b"anything", name)
    assert word in str(e.value)
    assert "CSV or Excel" in str(e.value)


# --- documents: PDF statements and decks ---------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def doc(name):
    return ingest.parse_upload((FIXTURES / name).read_bytes(), name)


def test_pdf_statement_without_ruled_lines_is_read():
    """Statement PDFs draw no cell borders and separate columns with one
    space, so the figures are peeled off the end of each line."""
    p = doc("pl_statement.pdf")
    assert p["source_kind"] == "pdf" and p["sheet"] == "Page 1"
    assert p["orientation"] == "rows"
    assert p["suggested_mapping"]["revenue"]["label"] == "Net product revenue"
    assert p["suggested_mapping"]["cost_of_revenue"]["label"] == "Cost of product sales"
    assert p["default_period"] == "FY2025"


def test_pdf_units_come_from_the_page_not_the_table():
    """'(USD in thousands)' is printed above a statement, never inside it."""
    p = doc("pl_statement.pdf")
    assert p["detected_units"] == "thousands"
    m = {k: v["label"] for k, v in p["suggested_mapping"].items()}
    e = ingest.extract(p["upload_id"], m, p["default_period"], "thousands")
    assert e["financials"]["revenue"] == pytest.approx(340_000_000)


def test_pdf_extraction_is_flagged_for_checking():
    assert "read out of a PDF" in doc("pl_statement.pdf")["extraction_note"]


def test_deck_table_is_read_from_the_slide_it_is_on():
    p = doc("board_deck.pptx")
    assert p["source_kind"] == "deck" and p["sheet"] == "Slide 2"
    assert p["suggested_mapping"]["revenue"]["label"] == "Net product revenue"
    assert p["extraction_note"]


def test_bracketed_expenses_survive_document_extraction():
    p = doc("board_deck.pptx")
    m = {k: v["label"] for k, v in p["suggested_mapping"].items()}
    e = ingest.extract(p["upload_id"], m, p["default_period"], "thousands")
    assert e["financials"]["ga"] == pytest.approx(47_000_000)   # printed (47,000)


def test_corrupt_document_fails_with_a_message_not_a_traceback():
    with pytest.raises(ValueError) as e:
        ingest.parse_upload(b"not really a pdf", "broken.pdf")
    assert "broken.pdf" in str(e.value)


def test_scanned_pdf_is_refused_rather_than_guessed():
    """A PDF with no text layer is a photo; OCR is out of scope on purpose."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas
    import io as _io
    buf = _io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.rect(72, 600, 200, 100, fill=0)      # a drawing, no text at all
    c.showPage()
    c.save()
    with pytest.raises(ValueError) as e:
        ingest.parse_upload(buf.getvalue(), "scan.pdf")
    assert "scan or a photo" in str(e.value)


def test_legacy_xls_uses_the_xlrd_engine():
    """Excel 97-2003 is still what many finance teams export."""
    assert ingest.SPREADSHEET_ENGINES[".xls"] == "xlrd"
    import importlib
    importlib.import_module("xlrd")  # fails the test if the dependency is gone


def _workbook(sheets: dict) -> bytes:
    import io as _io
    buf = _io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, frame in sheets.items():
            frame.to_excel(w, sheet_name=name, index=False)
    return buf.getvalue()


PL_SHEET = pd.DataFrame({
    "Line item": ["Net Product Revenue", "Cost of Goods Sold",
                  "General & Administrative", "Research & Development"],
    "FY2024": [310000, -198400, -44950, -11160],
    "FY2025": [340000, -210000, -47000, -12000],
})
COVER = pd.DataFrame({"Note": ["Confidential board pack"], "Date": ["2025"]})
ASSUMPTIONS = pd.DataFrame({"Assumption": ["FX", "Inflation"], "Value": [1.1, 0.03]})


def test_workbook_reads_the_sheet_that_looks_like_a_pl():
    """Reading whichever sheet is first benchmarks the cover page."""
    data = _workbook({"Cover": COVER, "Assumptions": ASSUMPTIONS, "P&L": PL_SHEET})
    p = ingest.parse_upload(data, "workbook.xlsx")
    assert p["sheet"] == "P&L"
    assert p["sheets"] == ["Cover", "Assumptions", "P&L"]
    assert p["suggested_mapping"]["revenue"]["label"] == "Net Product Revenue"


def test_workbook_sheet_can_be_overridden():
    data = _workbook({"Cover": COVER, "P&L": PL_SHEET})
    p = ingest.parse_upload(data, "workbook.xlsx", sheet="Cover")
    assert p["sheet"] == "Cover"
    assert p["warning"], "a sheet with no revenue line must warn"


def test_csv_reports_no_sheets():
    p = parse("pharma_pl_line_items_thousands.csv")
    assert p["sheet"] is None and p["sheets"] == []
