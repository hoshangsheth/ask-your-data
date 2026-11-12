"""
Upload parsing and cleaning (app/datasets/formats.py, cleaning.py, profile.py): every supported
format becomes clean, typed SQL tables, and bad files fail with clear messages.
"""

import pytest

from app.datasets.cleaning import TooLarge, clean_tables, safe_identifier
from app.datasets.formats import SUPPORTED_EXTENSIONS, UnreadableFile, UnsupportedFile, read_tables
from app.datasets.profile import DatasetMeta, profile_table, schema_text, suggest_questions
from tests import sample_files as files


def tables_for(data: bytes, filename: str):
    return clean_tables(read_tables(data, filename))


# Formats holding the 6-row sales table: (builder, filename, expected columns subset)
SALES_FORMATS = [
    (files.csv, "sales.csv"),
    (files.semicolon_csv, "sales.csv"),
    (files.tsv, "sales.tsv"),
    (files.text_table, "sales.txt"),
    (files.xlsx, "sales.xlsx"),
    (files.ods, "sales.ods"),
    (files.json_records, "sales.json"),
    (files.jsonl, "sales.jsonl"),
    (files.parquet, "sales.parquet"),
    (files.feather, "sales.feather"),
    (files.xml, "sales.xml"),
    (files.html, "sales.html"),
    (files.docx_table, "sales.docx"),
    (files.sqlite_db, "sales.sqlite"),
    (files.stata, "sales.dta"),
]


@pytest.mark.parametrize("builder, filename", SALES_FORMATS, ids=[f for _, f in SALES_FORMATS])
def test_every_format_becomes_a_sales_table(builder, filename):
    tables = tables_for(builder(), filename)
    sales = tables[0]
    assert len(sales.frame) == 6
    assert "region" in sales.frame.columns
    assert sorted(sales.frame["region"].unique()) == ["East", "North", "South", "West"]
    units = sales.frame["units"]
    assert units.sum() == 23  # numbers arrive as numbers, whatever the format


def test_text_numbers_and_dates_are_typed():
    t = tables_for(files.csv(), "sales.csv")[0]
    assert list(t.frame.columns) == ["region", "order_date", "amount", "units"]  # "Amount (₹)" -> amount
    assert t.frame["amount"].sum() == 10300  # "1,200" -> 1200
    assert t.frame["order_date"].iloc[0] == "2025-01-05" and "order_date" in t.date_columns


def test_excel_keeps_every_sheet():
    names = [t.name for t in tables_for(files.xlsx(), "book.xlsx")]
    assert names == ["sales", "managers"]


def test_nested_json_is_flattened():
    t = tables_for(files.json_nested(), "orders.json")[0]
    assert t.name == "orders" and {"customer_name", "customer_city", "total"} <= set(t.frame.columns)


def test_pdf_tables_and_text():
    table = tables_for(files.pdf_table(), "report.pdf")[0]
    assert list(table.frame.columns) == ["region", "units"] and table.frame["units"].sum() == 23
    text = tables_for(files.pdf_text(), "minutes.pdf")[0]
    assert list(text.frame.columns) == ["line_number", "text", "word_count"]


def test_prose_text_becomes_lines_table():
    t = tables_for(files.text_prose(), "notes.txt")[0]
    assert len(t.frame) == 3 and "text" in t.frame.columns


@pytest.mark.parametrize(
    "data, filename, error",
    [
        (b"anything", "virus.exe", UnsupportedFile),
        (b"", "empty.csv", UnreadableFile),
        (b"{not json", "bad.json", UnreadableFile),
        (b"not a database", "fake.sqlite", UnreadableFile),
        (b"PK\x03\x04garbage", "broken.xlsx", UnreadableFile),
    ],
)
def test_bad_files_fail_clearly(data, filename, error):
    with pytest.raises(error):
        read_tables(data, filename)


def test_row_limit(monkeypatch):
    import app.datasets.cleaning as cleaning

    monkeypatch.setattr(cleaning, "MAX_ROWS", 3)
    with pytest.raises(TooLarge, match="rows"):
        tables_for(files.csv(), "sales.csv")


def test_safe_identifiers():
    assert safe_identifier("Order Date (UTC)", "x") == "order_date_utc"
    assert safe_identifier("2024 Sales", "x") == "c_2024_sales"
    assert safe_identifier("select", "x") == "select_value"
    assert safe_identifier("Unnamed: 3", "column_4") == "column_4"
    assert safe_identifier("Café ₹", "x") == "cafe"


def test_supported_extensions_cover_common_formats():
    for ext in (
        ".csv",
        ".tsv",
        ".txt",
        ".xlsx",
        ".xls",
        ".ods",
        ".json",
        ".jsonl",
        ".parquet",
        ".xml",
        ".html",
        ".docx",
        ".pdf",
        ".sqlite",
        ".db",
        ".dta",
        ".sas7bdat",
    ):
        assert ext in SUPPORTED_EXTENSIONS


def test_profile_schema_text_and_suggestions():
    t = tables_for(files.csv(), "sales.csv")[0]
    meta = DatasetMeta(
        id="abc123abc123",
        name="sales",
        filename="sales.csv",
        file_format="csv",
        created_at="2026-01-01",
        size_bytes=1,
        tables=[profile_table(t)],
    )
    cols = {c.name: c for c in meta.tables[0].columns}
    assert cols["units"].type == "INTEGER" and cols["order_date"].type == "DATE" and cols["region"].complete_values
    text = schema_text(meta)
    assert "TABLE sales" in text and "Values: East, North, South, West" in text and "strftime" in text
    assert 'header in file: "Amount (₹)"' in text  # units survive the renaming
    suggestions = suggest_questions(meta)
    assert suggestions[0] == "What is the total amount by region?"  # money-like measure first
    assert any("monthly" in s for s in suggestions)
