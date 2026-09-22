"""P&L upload parsing and field mapping.

Three things real finance exports get wrong-footed on, each of which silently
produces a wrong benchmark if missed:

1. ORIENTATION. A CFO's P&L export usually lists line items down the rows and
   periods across the columns ("Revenue | FY2023 | FY2024"). A system export
   is often the reverse, one column per line item. Both are detected.
2. UNITS. Statements are frequently "in thousands". Ratios survive that, but
   revenue does not: a $420M company read as $420K lands in the wrong size
   band, so it is compared with the wrong peers and every dollar figure is off
   by 1000x. Unit hints are detected and the user confirms.
3. SIGN. Many exports show expenses as negatives. Taken literally, every cost
   ratio goes negative and quietly drops out as "unavailable". Expense lines
   are normalised to positive; income lines keep their sign.

Mapping is only ever SUGGESTED. The user confirms it before anything is
benchmarked, because a wrong mapping yields a confident, plausible, wrong
answer.
"""

import io
import re
import uuid
from typing import List, Optional

import pandas as pd

from core import documents

# field -> (label, synonyms). Synonyms are normalised the same way as headers.
FIELDS = {
    "revenue": ("Revenue", [
        "total revenue", "net revenue", "revenue", "revenues", "net sales",
        "total net sales", "sales", "turnover", "total revenues",
        # Drug-company wording: 10-Ks report "net product revenue" alongside
        # collaboration and royalty lines.
        "net product revenue", "net product revenues", "product revenue net",
        "total net revenue", "total net revenues"]),
    "cost_of_revenue": ("Cost of revenue", [
        "cost of revenue", "cost of revenues", "cost of goods sold", "cogs",
        "cost of sales", "cost of goods and services sold",
        "cost of product sales", "cost of product revenue"]),
    "ga": ("G&A", [
        "general and administrative", "g and a", "general administrative",
        "administrative expenses", "general and admin", "admin expenses",
        "administration"]),
    "sales_marketing": ("Sales & marketing", [
        "sales and marketing", "selling and marketing", "s and m",
        "selling expenses", "sales marketing"]),
    "overhead": ("SG&A (total)", [
        "sg and a", "selling general and administrative", "sga",
        "selling general administrative", "total sg and a"]),
    "rnd": ("R&D", [
        "research and development", "r and d", "research development"]),
    "facilities": ("Facilities / rent", [
        "rent and occupancy", "occupancy", "facilities", "rent",
        "operating lease cost", "lease expense", "facility costs",
        "rent expense", "facilities and occupancy"]),
    "advertising": ("Advertising", [
        "advertising", "advertising expense", "advertising and promotion"]),
    "capex": ("CAPEX", [
        "capital expenditures", "capital expenditure", "capex",
        "purchases of property plant and equipment", "purchase of ppe"]),
    "depreciation_amortization": ("Depreciation & amortisation", [
        "depreciation and amortization", "depreciation and amortisation",
        "d and a", "depreciation amortization", "depreciation"]),
    "operating_income": ("Operating income (EBIT)", [
        "operating income", "operating profit", "income from operations",
        "ebit", "operating loss", "operating income loss"]),
    "ebitda": ("EBITDA", ["ebitda", "adjusted ebitda", "reported ebitda"]),
    "net_income": ("Net income", [
        "net income", "net profit", "net loss", "net income loss",
        "net earnings"]),
    "professional_fees": ("Professional fees", [
        "professional fees", "consulting fees", "legal and professional",
        "professional services"]),
}

# Expense lines are normalised to positive magnitudes; see module docstring.
EXPENSE_FIELDS = {"cost_of_revenue", "ga", "sales_marketing", "overhead",
                  "rnd", "facilities", "advertising", "capex",
                  "depreciation_amortization", "professional_fees"}

UNIT_MULTIPLIERS = {"dollars": 1.0, "thousands": 1e3, "millions": 1e6}

# Shown whenever figures were lifted out of a document rather than read from a
# spreadsheet cell: the column structure is inferred, so the confirmation step
# matters more here than anywhere else.
EXTRACTION_NOTES = {
    "pdf": "Figures were read out of a PDF, so the columns are inferred. "
           "Check each mapped value against the document before continuing.",
    "deck": "Figures were read out of a slide table, so the columns are "
            "inferred. Check each mapped value before continuing.",
}

_UPLOADS: dict = {}
MAX_PREVIEW = 30


def normalise(text) -> str:
    s = str(text).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _best_pattern(label_norm: str):
    """Longest synonym contained in the label as whole words, if any.

    Whole-word containment stops "rent" matching "current assets"; preferring
    the longest pattern stops "sales" claiming "sales and marketing" or
    "cost of sales".
    """
    padded = f" {label_norm} "
    best = None
    for field, (_, pats) in FIELDS.items():
        for p in pats:
            pn = normalise(p)
            if f" {pn} " in padded:
                exact = pn == label_norm
                score = (exact, len(pn))
                if best is None or score > best[0]:
                    best = (score, field, exact)
    return best


def suggest_mapping(labels: list) -> dict:
    """field -> {label, confidence}. Greedy by match quality."""
    candidates = []
    for label in labels:
        n = normalise(label)
        if not n:
            continue
        hit = _best_pattern(n)
        if hit:
            (exact, length), field, _ = hit
            candidates.append(((exact, length), field, label))

    candidates.sort(key=lambda c: c[0], reverse=True)
    mapping, taken = {}, set()
    for (exact, _), field, label in candidates:
        if field in mapping or label in taken:
            continue
        mapping[field] = {"label": label,
                          "confidence": "exact" if exact else "partial"}
        taken.add(label)
    return mapping


def detect_units(texts: list) -> Optional[str]:
    """Look for a units hint in label text only.

    Cells without letters are skipped: a plain figure like "420,000" normalises
    to "420 000", and treating that "000" as a units hint would flag every
    dollar-denominated file as thousands and inflate it 1000x.
    """
    words = [normalise(t) for t in texts
             if t is not None and re.search(r"[A-Za-z]", str(t))]
    blob = " " + " ".join(words) + " "
    if re.search(r"\b(in thousands|thousands|000s|usd 000|in 000)\b", blob):
        return "thousands"
    if re.search(r"\b(in millions|millions|usd m|usd mm|in mm)\b", blob):
        return "millions"
    return None


_YEAR = re.compile(r"(?:fy\s*)?((?:19|20)\d{2})", re.IGNORECASE)


def year_in(text) -> Optional[int]:
    m = _YEAR.search(str(text))
    return int(m.group(1)) if m else None


_NUM_JUNK = re.compile(r"[,$\s%£€]")


def to_number(value) -> Optional[float]:
    """Spreadsheet cell -> float. Handles separators, currency, (negatives),
    k/m/b suffixes and the usual blanks."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return None if pd.isna(f) else f
    s = str(value).strip()
    if not s or s.lower() in {"na", "n/a", "-", "--", "—", "nan", "none", "null"}:
        return None
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    mult = 1.0
    tail = s[-1:].lower()
    if tail in {"k", "m", "b"} and len(s) > 1 and s[-2].isdigit():
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[tail]
        s = s[:-1]
    s = _NUM_JUNK.sub("", s)
    try:
        f = float(s)
    except ValueError:
        return None
    return (-f if negative else f) * mult


# Spreadsheets and delimited text are parsed deterministically, cell by cell.
# Everything else a user might drag in -- a board deck, a scanned statement, a
# screenshot -- would need layout inference or OCR, where a misread digit
# becomes a confident wrong benchmark. Those are refused with instructions
# rather than guessed at.
SPREADSHEET_ENGINES = {
    ".xlsx": "openpyxl", ".xlsm": "openpyxl", ".xltx": "openpyxl",
    ".xls": "xlrd",       # legacy BIFF, needs xlrd >= 2.0.1
    ".ods": "odf",
}
TEXT_SUFFIXES = (".csv", ".tsv", ".txt")
# Documents whose tables can be read as printed. core/documents.py returns raw
# cell grids; everything after that is the spreadsheet path, unchanged.
DOCUMENT_READERS = {
    ".pdf": ("pdf", documents.pdf_tables),
    ".pptx": ("deck", documents.pptx_tables),
}
UNSUPPORTED = {
    ".ppt": "PowerPoint 97-2003",   # binary format; python-pptx reads .pptx only
    ".doc": "Word", ".docx": "Word",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".heic": "image", ".bmp": "image", ".tif": "image",
    ".tiff": "image", ".zip": "archive", ".msg": "email", ".eml": "email",
}


def _suffix(filename: str) -> str:
    name = (filename or "").lower()
    return name[name.rfind("."):] if "." in name else ""


def _pl_score(df: pd.DataFrame) -> tuple:
    """How much this sheet looks like a P&L: recognised line items, then size.

    A real workbook holds a cover sheet, assumptions and several statements.
    Reading whichever sheet happens to be first is how an engine ends up
    benchmarking a balance sheet.
    """
    if df is None or df.empty or len(df.columns) < 2:
        return (0, 0)
    labels = [str(c) for c in df.columns]
    labels += [str(v) for v in df.iloc[:, 0].tolist()]
    recognised = len(suggest_mapping(labels))
    numbers = int(sum(df[c].map(to_number).notna().sum() for c in df.columns))
    return (recognised, numbers)


def _best_sheet(book: dict) -> str:
    return max(book, key=lambda name: _pl_score(book[name]))


def _headers(row: List[str], width: int) -> List[str]:
    """Unique, non-empty column names."""
    out, seen = [], set()
    for i in range(width):
        name = (row[i] if i < len(row) else "").strip() or f"Column {i + 1}"
        while name in seen:
            name += " "
        seen.add(name)
        out.append(name)
    return out


def _grid_frame(grid: List[List[str]]) -> pd.DataFrame:
    """A raw cell grid as a frame, with the first row as headers when it is one.

    A statement page can start straight at "Revenue 310,000 291,000" with the
    period header on an earlier line. Taking that first data row as the header
    would lose a line item and invent a period called "310,000".
    """
    if not grid:
        return pd.DataFrame()
    width = max(len(r) for r in grid)
    head = grid[0]
    figures = sum(1 for c in head[1:] if to_number(c) is not None)
    if figures and figures >= len(head) - 1:
        columns = ["Line item"] + [f"Value {i}" for i in range(1, width)]
        body = grid
    else:
        columns = _headers(head, width)
        body = grid[1:]
    rows = [r + [""] * (width - len(r)) for r in body]
    return pd.DataFrame(rows, columns=columns)


def _read(content: bytes, filename: str, sheet: str | None = None):
    """Returns (frame, section, all sections, source kind, surrounding text)."""
    suffix = _suffix(filename)

    if suffix in UNSUPPORTED:
        raise ValueError(
            f"{UNSUPPORTED[suffix]} files are not supported. The engine reads "
            f"figures cell by cell so nothing is misread: export the P&L as CSV "
            f"or Excel (.xlsx) and upload that.")

    if suffix in DOCUMENT_READERS:
        kind, reader = DOCUMENT_READERS[suffix]
        candidates = reader(content, to_number)
        sections = [name for name, _, _ in candidates]
        by_name = {name: (grid, text) for name, grid, text in candidates}
        chosen = sheet if sheet in by_name else max(
            candidates, key=lambda c: _pl_score(_grid_frame(c[1])))[0]
        grid, context = by_name[chosen]
        return _grid_frame(grid), chosen, sections, kind, context

    if suffix in SPREADSHEET_ENGINES:
        engine = SPREADSHEET_ENGINES[suffix]
        try:
            book = pd.read_excel(io.BytesIO(content), header=0, engine=engine,
                                 sheet_name=None)
        except ImportError as e:
            raise ValueError(
                f"This build cannot open {suffix} files ({e}). Re-save the file "
                f"as .xlsx or CSV, or install the '{engine}' package."
                ) from e
        if not book:
            raise ValueError("That workbook has no sheets.")
        names = list(book)
        chosen = sheet if sheet in book else _best_sheet(book)
        return book[chosen], chosen, names, "workbook", ""

    if suffix and suffix not in TEXT_SUFFIXES:
        raise ValueError(
            f"{suffix} files are not supported. Upload a CSV or Excel P&L.")

    for enc in ("utf-8-sig", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(content), encoding=enc), None, [], "file", ""
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode the file as UTF-8 or Windows-1252. If it "
                     "is a spreadsheet, save it as .xlsx or CSV first.")


_TOTAL_RE = re.compile(r"\b(total|fy|full[\s-]?year|ytd|annual)\b", re.I)
_QUARTER_RE = re.compile(r"\bq\s*([1-4])\b", re.I)
_MONTH_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.I)


def _is_total(label) -> bool:
    return bool(_TOTAL_RE.search(str(label)))


def _is_quarter(label) -> bool:
    return bool(_QUARTER_RE.search(str(label)))


def _is_month(label) -> bool:
    return bool(_MONTH_RE.search(str(label)))


def _is_subperiod(label) -> bool:
    return _is_quarter(label) or _is_month(label)


def choose_default_period(periods: list) -> str | None:
    """The column to benchmark: the latest FULL year.

    Peer ratios are annual, and the revenue band that picks the peer set is
    annual too, so benchmarking one quarter puts a $480M company in the $100M
    band. Prefer an annual/total column for the latest year; failing that, the
    latest year's last quarter, which extract() then sums with its siblings.
    Picking `max(year)` alone returned Q1 for a file whose five columns all
    said 2025.
    """
    if not periods:
        return None
    years = [p["year"] for p in periods if p.get("year")]
    latest = max(years) if years else None
    same = [p for p in periods if p.get("year") == latest] if latest else list(periods)
    annual = [p for p in same if not _is_subperiod(p["label"])]
    if annual:
        totals = [p for p in annual if _is_total(p["label"])]
        return (totals or annual)[0]["key"]
    quarters = [p for p in same if _is_quarter(p["label"])]
    if quarters:
        return max(quarters,
                   key=lambda p: int(_QUARTER_RE.search(p["label"]).group(1)))["key"]
    return same[-1]["key"]


def _columns_for_period(up: dict, period: str) -> list:
    """The column keys that make up the period being benchmarked.

    A quarter whose year has all four quarters in the file is annualised by
    summing them; anything else is read as the single column it names.
    """
    per = up.get("periods") or []
    if up.get("orientation") != "rows" or not _is_quarter(period):
        return [period]
    year = next((p.get("year") for p in per if p["key"] == period), None)
    quarters = [p["key"] for p in per
                if p.get("year") == year and _is_quarter(p["key"])]
    if len({_QUARTER_RE.search(k).group(1) for k in quarters}) == 4:
        return sorted(quarters,
                      key=lambda k: int(_QUARTER_RE.search(k).group(1)))
    return [period]


def parse_upload(content: bytes, filename: str,
                 sheet: str | None = None) -> dict:
    try:
        df, sheet_name, sheet_names, source_kind, context = _read(
            content, filename, sheet)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not read {filename or 'the file'}: {e}") from e

    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if df.empty or len(df.columns) < 2:
        raise ValueError("The file needs at least two columns of data.")
    df.columns = [str(c).strip() for c in df.columns]

    headers = list(df.columns)
    first_col = [str(v).strip() for v in df.iloc[:, 0].tolist()]

    col_map = suggest_mapping(headers)
    row_map = suggest_mapping(first_col)

    # Line items down the rows is the usual CFO layout; choose whichever
    # orientation recognises more fields. When neither side matches a synonym
    # at all -- exactly the file an AI-assisted mapping later has to rescue --
    # that comparison is 0-to-0 and defaulting to "columns" is a coin flip that
    # is wrong most of the time. Break the tie on which axis actually holds
    # PERIODS: a P&L's periods are years (or FYxx/Qx), and they almost always
    # run across the header row, not down the first column.
    if len(row_map) == len(col_map):
        header_periods = sum(1 for h in headers[1:] if year_in(h) is not None)
        row_periods = sum(1 for v in first_col if year_in(v) is not None)
        prefer_rows = header_periods >= row_periods
    else:
        prefer_rows = len(row_map) > len(col_map)

    if prefer_rows:
        orientation = "rows"
        labels = first_col
        mapping = row_map
        periods = [{"key": h, "label": h, "year": year_in(h)}
                   for h in headers[1:]
                   if df[h].map(to_number).notna().any()]
    else:
        orientation = "columns"
        labels = headers
        mapping = col_map
        fy_col = next((h for h in headers if normalise(h) in
                       {"fiscal year", "year", "fy", "period"}), None)
        periods = []
        for i in range(len(df)):
            yr = year_in(df.iloc[i][fy_col]) if fy_col else None
            periods.append({"key": str(i),
                            "label": f"FY{yr}" if yr else f"Row {i + 1}",
                            "year": yr})

    if not mapping.get("revenue"):
        hint = ("No revenue line was recognised. Map it manually below; "
                "revenue is required to benchmark anything.")
    else:
        hint = None

    upload_id = uuid.uuid4().hex[:12]
    # `periods` is kept alongside the frame, not just returned in the preview:
    # multi-period analysis (core/trends.py) needs the same detection this pass
    # already did, and recomputing it there would let the two drift apart.
    _UPLOADS[upload_id] = {"df": df, "orientation": orientation,
                           "filename": filename, "sheet": sheet_name,
                           "source_kind": source_kind, "periods": periods}

    preview = df.head(MAX_PREVIEW).astype(object).where(
        pd.notna(df.head(MAX_PREVIEW)), None)

    return {
        "upload_id": upload_id,
        "filename": filename,
        "sheet": sheet_name,
        "sheets": sheet_names,
        "source_kind": source_kind,
        "extraction_note": EXTRACTION_NOTES.get(source_kind),
        "orientation": orientation,
        "labels": [l for l in labels if l and l.lower() != "nan"],
        "periods": periods,
        "default_period": choose_default_period(periods),
        "suggested_mapping": mapping,
        "detected_units": detect_units(
            headers + first_col + [filename, context]),
        "fields": [{"key": k, "label": v[0],
                    "required": k == "revenue"} for k, v in FIELDS.items()],
        "preview": {"columns": headers,
                    "rows": preview.values.tolist()},
        "warning": hint,
    }


def label_samples(upload_id: str, period: Optional[str] = None) -> dict:
    """One printed value per label, so a mapper can tell a total from a line."""
    up = _UPLOADS.get(upload_id)
    if up is None:
        return {}
    df, out = up["df"], {}
    if up["orientation"] == "rows":
        col = period if period in df.columns else (
            df.columns[-1] if len(df.columns) > 1 else None)
        for _, row in df.iterrows():
            label = str(row.iloc[0]).strip()
            if label and col is not None:
                out.setdefault(label, str(row[col]).strip())
    else:
        first = df.iloc[0] if len(df) else None
        for c in df.columns:
            if first is not None:
                out.setdefault(str(c).strip(), str(first[c]).strip())
    return {k: v for k, v in out.items() if k and v and v.lower() != "nan"}


def extract(upload_id: str, mapping: dict, period: str,
            units: str = "dollars", annualise: bool = True) -> dict:
    """Pull mapped values for one period, scaled to dollars, signs normalised."""
    up = _UPLOADS.get(upload_id)
    if up is None:
        raise ValueError("Upload not found - it may have expired when the "
                         "server restarted. Upload the file again.")
    if units not in UNIT_MULTIPLIERS:
        raise ValueError(f"units must be one of {sorted(UNIT_MULTIPLIERS)}")
    mult = UNIT_MULTIPLIERS[units]
    df = up["df"]
    # A quarter with all four siblings in the file is read as the year's sum:
    # peer ratios and the revenue band are annual, and one quarter's revenue
    # dropped a $480M company into the $100M peer band.
    columns = _columns_for_period(up, period) if annualise else [period]

    values, missing_labels = {}, []
    for field, label in mapping.items():
        if not label or field not in FIELDS:
            continue
        if up["orientation"] == "rows":
            if period not in df.columns:
                raise ValueError(f"Period '{period}' is not a column in the file.")
            hits = df.index[df.iloc[:, 0].astype(str).str.strip() == label]
            if len(hits) == 0:
                missing_labels.append(label)
                continue
            parts = [to_number(df.loc[hits[0], c]) for c in columns
                     if c in df.columns]
            parts = [x for x in parts if x is not None]
            raw = sum(parts) if parts else None
        else:
            try:
                row = df.iloc[int(period)]
            except (ValueError, IndexError) as e:
                raise ValueError(f"Row '{period}' is not in the file.") from e
            if label not in df.columns:
                missing_labels.append(label)
                continue
            raw = row[label]

        v = raw if isinstance(raw, (int, float)) else to_number(raw)
        if v is None:
            continue
        v *= mult
        if field in EXPENSE_FIELDS:
            v = abs(v)
        values[field] = v

    return {"financials": values, "missing_labels": missing_labels,
            "orientation": up["orientation"],
            "annualised_from": columns if len(columns) > 1 else None}
