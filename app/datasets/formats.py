"""
File readers: one function per format, each returning raw tables as (name, DataFrame) pairs.

Supported formats (extension -> reader):
    Delimited text   .csv .tsv .tab .psv .txt (delimiter auto-detected; plain prose -> a lines table)
    Spreadsheets     .xlsx .xlsm .xls .ods         (one table per non-empty sheet)
    JSON             .json .jsonl .ndjson          (nested objects are flattened)
    Columnar         .parquet .feather
    Markup           .xml .html .htm               (HTML: every <table> on the page)
    Documents        .docx (tables, else paragraphs)  .pdf (tables, else text lines)
    Databases        .sqlite .sqlite3 .db          (every table)
    Statistics       .dta (Stata) .sas7bdat .xpt (SAS)

Readers never touch the database and never use the uploaded file name as a path; they only
get bytes. Raise UnsupportedFile / UnreadableFile with a message that is safe to show users.
"""

import io
import json
import os
import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path

import pandas as pd

RawTables = list[tuple[str, pd.DataFrame]]

MAX_PDF_PAGES = 50  # parsing PDFs is CPU-heavy; enough for reports, bounded for safety


class UnsupportedFile(ValueError):
    """The file type is not supported."""


class UnreadableFile(ValueError):
    """The file type is supported but its content could not be read as tables."""


# ---- Delimited text -------------------------------------------------------------------------
def _decode(data: bytes) -> str:
    """Decode text trying UTF-8 (with/without BOM) first, then common Windows encodings."""
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_delimited(data: bytes, stem: str, sep: str | None = None) -> RawTables:
    text = _decode(data)
    if not text.strip():
        raise UnreadableFile("the file is empty")
    try:
        # sep=None makes pandas sniff the delimiter (comma, semicolon, tab, pipe, ...).
        df = pd.read_csv(io.StringIO(text), sep=sep, engine="python")
    except Exception as e:  # pandas raises several parser error types
        raise UnreadableFile(f"could not read the file as a table: {str(e).splitlines()[0][:200]}") from e
    return [(stem, df)]


def _read_text(data: bytes, stem: str) -> RawTables:
    """A .txt file: a delimited table if it looks like one, otherwise one row per line."""
    text = _decode(data)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise UnreadableFile("the file is empty")
    sample = lines[:20]
    for delim in (",", "\t", ";", "|"):
        counts = [ln.count(delim) for ln in sample]
        if min(counts) >= 1 and len(set(counts)) == 1:  # same number of delimiters on every line
            return _read_delimited(data, stem, sep=delim)
    return [(stem, _lines_table(lines))]


def _lines_table(lines: list[str]) -> pd.DataFrame:
    """Unstructured text as a table: line number, text, word count."""
    return pd.DataFrame(
        {
            "line_number": range(1, len(lines) + 1),
            "text": [ln.strip() for ln in lines],
            "word_count": [len(ln.split()) for ln in lines],
        }
    )


# ---- Spreadsheets ---------------------------------------------------------------------------
def _read_excel(engine: str | None) -> Callable[[bytes, str], RawTables]:
    def read(data: bytes, stem: str) -> RawTables:
        try:
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, engine=engine)
        except Exception as e:
            raise UnreadableFile(f"could not open the spreadsheet: {str(e).splitlines()[0][:200]}") from e
        tables = [
            (name if len(sheets) > 1 else stem, df) for name, df in sheets.items() if not df.dropna(how="all").empty
        ]
        if not tables:
            raise UnreadableFile("every sheet is empty")
        return tables

    return read


# ---- JSON -----------------------------------------------------------------------------------
def _records_to_frame(records: list) -> pd.DataFrame:
    if records and all(isinstance(r, dict) for r in records):
        return pd.json_normalize(records, sep="_")  # nested objects -> parent_child columns
    return pd.DataFrame({"value": records})


def _read_json(data: bytes, stem: str) -> RawTables:
    try:
        obj = json.loads(_decode(data))
    except json.JSONDecodeError as e:
        raise UnreadableFile(f"invalid JSON: {e.msg} (line {e.lineno})") from e
    if isinstance(obj, list):
        return [(stem, _records_to_frame(obj))]
    if isinstance(obj, dict):
        # {"orders": [...], "customers": [...]} -> one table per list of records.
        lists = [(k, v) for k, v in obj.items() if isinstance(v, list) and v]
        if lists:
            return [(k, _records_to_frame(v)) for k, v in lists]
        return [(stem, pd.json_normalize(obj, sep="_"))]
    raise UnreadableFile("the JSON does not contain records")


def _read_json_lines(data: bytes, stem: str) -> RawTables:
    records = []
    for n, line in enumerate(_decode(data).splitlines(), 1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise UnreadableFile(f"invalid JSON on line {n}: {e.msg}") from e
    if not records:
        raise UnreadableFile("the file is empty")
    return [(stem, _records_to_frame(records))]


# ---- Columnar / statistical -----------------------------------------------------------------
def _read_with(reader: Callable[..., pd.DataFrame], **kwargs) -> Callable[[bytes, str], RawTables]:
    def read(data: bytes, stem: str) -> RawTables:
        try:
            return [(stem, reader(io.BytesIO(data), **kwargs))]
        except Exception as e:
            raise UnreadableFile(f"could not read the file: {str(e).splitlines()[0][:200]}") from e

    return read


# ---- Markup ---------------------------------------------------------------------------------
def _read_xml(data: bytes, stem: str) -> RawTables:
    try:
        return [(stem, pd.read_xml(io.BytesIO(data)))]
    except Exception as e:
        raise UnreadableFile(f"could not find repeating records in the XML: {str(e).splitlines()[0][:200]}") from e


def _read_html(data: bytes, stem: str) -> RawTables:
    try:
        frames = pd.read_html(io.StringIO(_decode(data)))
    except ValueError as e:
        raise UnreadableFile("no <table> found in the HTML page") from e
    return [(f"{stem}_{i + 1}" if len(frames) > 1 else stem, df) for i, df in enumerate(frames)]


# ---- Documents ------------------------------------------------------------------------------
def _grid_to_frame(rows: list[list]) -> pd.DataFrame | None:
    """A 2-D grid (first row = header) as a DataFrame; None if it has no data rows."""
    rows = [
        [("" if c is None else str(c).strip()) for c in r] for r in rows if r and any(c not in (None, "") for c in r)
    ]
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = [h or f"column_{i + 1}" for i, h in enumerate(rows[0])]
    return pd.DataFrame(rows[1:], columns=header)


def _read_docx(data: bytes, stem: str) -> RawTables:
    import docx  # python-docx; imported lazily (only needed for Word files)

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        raise UnreadableFile("could not open the Word document") from e
    tables = []
    for i, t in enumerate(doc.tables, 1):
        df = _grid_to_frame([[cell.text for cell in row.cells] for row in t.rows])
        if df is not None:
            tables.append((f"{stem}_table_{i}" if len(doc.tables) > 1 else stem, df))
    if tables:
        return tables
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    if not paragraphs:
        raise UnreadableFile("the document has no tables or text")
    return [(stem, _lines_table(paragraphs))]


def _read_pdf(data: bytes, stem: str) -> RawTables:
    import pdfplumber  # imported lazily (only needed for PDFs)

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as e:
        raise UnreadableFile("could not open the PDF") from e
    tables, lines = [], []
    with pdf:
        for page in pdf.pages[:MAX_PDF_PAGES]:
            for grid in page.extract_tables():
                df = _grid_to_frame(grid)
                if df is not None:
                    tables.append(df)
            lines += (page.extract_text() or "").splitlines()
    if tables:
        # Tables with the same header (a table split across pages) are joined into one.
        merged: dict[tuple, list[pd.DataFrame]] = {}
        for df in tables:
            merged.setdefault(tuple(df.columns), []).append(df)
        groups = list(merged.values())
        return [
            (f"{stem}_table_{i + 1}" if len(groups) > 1 else stem, pd.concat(g, ignore_index=True))
            for i, g in enumerate(groups)
        ]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        raise UnreadableFile("the PDF has no extractable tables or text (it may be a scanned image)")
    return [(stem, _lines_table(lines))]


# ---- SQLite ---------------------------------------------------------------------------------
def _read_sqlite(data: bytes, stem: str) -> RawTables:
    if not data.startswith(b"SQLite format 3\x00"):
        raise UnreadableFile("not a SQLite database file")
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            names = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            tables = [(name, pd.read_sql_query(f'SELECT * FROM "{name.replace(chr(34), "")}"', conn)) for name in names]
        finally:
            conn.close()
    finally:
        os.unlink(path)
    if not tables:
        raise UnreadableFile("the database has no tables")
    return tables


# ---- Registry -------------------------------------------------------------------------------
READERS: dict[str, Callable[[bytes, str], RawTables]] = {
    ".csv": lambda d, s: _read_delimited(d, s),
    ".tsv": lambda d, s: _read_delimited(d, s, sep="\t"),
    ".tab": lambda d, s: _read_delimited(d, s, sep="\t"),
    ".psv": lambda d, s: _read_delimited(d, s, sep="|"),
    ".txt": _read_text,
    ".xlsx": _read_excel("openpyxl"),
    ".xlsm": _read_excel("openpyxl"),
    ".xls": _read_excel("xlrd"),
    ".ods": _read_excel("odf"),
    ".json": _read_json,
    ".jsonl": _read_json_lines,
    ".ndjson": _read_json_lines,
    ".parquet": _read_with(pd.read_parquet),
    ".feather": _read_with(pd.read_feather),
    ".xml": _read_xml,
    ".html": _read_html,
    ".htm": _read_html,
    ".docx": _read_docx,
    ".pdf": _read_pdf,
    ".sqlite": _read_sqlite,
    ".sqlite3": _read_sqlite,
    ".db": _read_sqlite,
    ".dta": _read_with(pd.read_stata),
    ".sas7bdat": _read_with(pd.read_sas, format="sas7bdat"),
    ".xpt": _read_with(pd.read_sas, format="xport"),
}

SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(READERS)


def read_tables(data: bytes, filename: str) -> RawTables:
    """Read an uploaded file into raw tables, choosing the reader by extension."""
    ext = Path(filename).suffix.lower()
    if ext not in READERS:
        raise UnsupportedFile(
            f"'{ext or filename}' files are not supported. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    stem = Path(filename).stem or "data"
    return READERS[ext](data, stem)
