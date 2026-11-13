"""
Builders for small sample files in every supported upload format (used by the upload tests).

Each builder returns the file's bytes. The data is the same small sales table everywhere, so tests
can check that every format arrives as the same SQL table.
"""

import io
import os
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd

SALES = pd.DataFrame(
    {
        "Region": ["North", "South", "East", "West", "South", "North"],
        "Order Date": ["2025-01-05", "2025-01-17", "2025-02-02", "2025-02-20", "2025-03-03", "2025-03-28"],
        "Amount (₹)": ["1,200", "2,500", "800", "1,750", "3,100", "950"],
        "Units": [3, 5, 2, 4, 7, 2],
    }
)
NUMERIC = SALES.assign(**{"Amount (₹)": [1200, 2500, 800, 1750, 3100, 950]})


def csv() -> bytes:
    return SALES.to_csv(index=False).encode()


def semicolon_csv() -> bytes:
    return SALES.to_csv(index=False, sep=";").encode()


def tsv() -> bytes:
    return SALES.to_csv(index=False, sep="\t").encode()


def text_table() -> bytes:
    return SALES.to_csv(index=False, sep="|").encode()


def text_prose() -> bytes:
    return b"Quarterly review notes\nRevenue grew in the South region.\nThe East region slowed down.\n"


def xlsx() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        NUMERIC.to_excel(w, sheet_name="Sales", index=False)
        pd.DataFrame({"Region": ["North", "South"], "Manager": ["Asha", "Ravi"]}).to_excel(
            w, sheet_name="Managers", index=False
        )
    return buf.getvalue()


def ods() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="odf") as w:
        NUMERIC.to_excel(w, sheet_name="Sales", index=False)
    return buf.getvalue()


def json_records() -> bytes:
    return NUMERIC.to_json(orient="records").encode()


def json_nested() -> bytes:
    return b'{"orders": [{"id": 1, "customer": {"name": "Asha", "city": "Pune"}, "total": 500}, {"id": 2, "customer": {"name": "Ravi", "city": "Delhi"}, "total": 900}]}'


def jsonl() -> bytes:
    return NUMERIC.to_json(orient="records", lines=True).encode()


def parquet() -> bytes:
    buf = io.BytesIO()
    NUMERIC.to_parquet(buf, index=False)
    return buf.getvalue()


def feather() -> bytes:
    buf = io.BytesIO()
    NUMERIC.to_feather(buf)
    return buf.getvalue()


def xml() -> bytes:
    return NUMERIC.rename(columns={"Amount (₹)": "Amount", "Order Date": "OrderDate"}).to_xml(index=False).encode()


def html() -> bytes:
    return f"<html><body><h1>Report</h1>{NUMERIC.to_html(index=False)}</body></html>".encode()


def docx_table() -> bytes:
    import docx

    doc = docx.Document()
    doc.add_paragraph("Sales report")
    table = doc.add_table(rows=1, cols=len(SALES.columns))
    for cell, name in zip(table.rows[0].cells, SALES.columns, strict=True):
        cell.text = name
    for _, row in SALES.iterrows():
        cells = table.add_row().cells
        for cell, value in zip(cells, row, strict=True):
            cell.text = str(value)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def pdf_table() -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=10)
    data = [["Region", "Units"], *[[r, str(u)] for r, u in zip(SALES["Region"], SALES["Units"], strict=True)]]
    with pdf.table() as table:
        for row in data:
            r = table.row()
            for value in row:
                r.cell(value)
    return bytes(pdf.output())


def pdf_text() -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    for line in ["Board meeting minutes", "Revenue grew 12 percent.", "Hiring is paused."]:
        pdf.cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def sqlite_db() -> bytes:
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        NUMERIC.rename(columns={"Amount (₹)": "amount", "Order Date": "order_date"}).to_sql("sales", conn, index=False)
        conn.close()
        return Path(path).read_bytes()
    finally:
        os.unlink(path)


def stata() -> bytes:
    buf = io.BytesIO()
    NUMERIC.rename(columns={"Amount (₹)": "amount", "Order Date": "order_date"}).to_stata(buf, write_index=False)
    return buf.getvalue()


def zip_of(entries: dict[str, bytes]) -> bytes:
    """A .zip holding the given files (name -> bytes)."""
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def relational_zip() -> bytes:
    """Two related tables, like an export of a small shop: customers and their orders."""
    customers = b"customer_id,city\nc1,Mumbai\nc2,Pune\nc3,Delhi\n"
    orders = b"order_id,customer_id,amount\no1,c1,100\no2,c1,250\no3,c2,80\no4,c3,40\n"
    return zip_of(
        {
            "shop/customers.csv": customers,
            "shop/orders.csv": orders,
            "shop/readme.md": b"not data",
            "__MACOSX/shop/._orders.csv": b"junk",
            "shop/.DS_Store": b"junk",
        }
    )
