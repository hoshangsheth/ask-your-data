"""
Make raw tables safe and useful as SQL tables.

    - table and column names become lower_snake_case ASCII, unique, never SQL keywords
    - fully empty rows/columns are dropped
    - text columns that are really numbers ("1,234", "₹500", "12%") become numbers
    - text columns that are really dates become ISO dates (YYYY-MM-DD) so SQL can group by month
    - size limits protect the server (rows, columns, tables)

Usage:
    tables = clean_tables(raw_tables)   # -> list[CleanTable]
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.core.lazy import lazy_module

pd = lazy_module("pandas")  # imported on first use: only uploads need it

MAX_TABLES = 50
MAX_COLUMNS = 300
MAX_ROWS = 2_000_000  # per table
MAX_TOTAL_ROWS = 3_000_000  # across all tables of one upload
CONVERT_THRESHOLD = 0.9  # share of non-empty values that must parse to change a column's type

_SQL_RESERVED = {
    "select",
    "from",
    "where",
    "group",
    "order",
    "by",
    "limit",
    "table",
    "join",
    "on",
    "as",
    "and",
    "or",
    "not",
    "null",
    "case",
    "when",
    "then",
    "else",
    "end",
    "union",
    "all",
    "distinct",
    "having",
    "in",
    "is",
    "like",
    "between",
    "index",
    "key",
    "primary",
    "foreign",
    "check",
    "default",
    "user",
    "date",
}
_NUMBER_JUNK = re.compile(r"[,\s₹$€£¥%]|^(rs\.?|inr|usd)", re.IGNORECASE)


class TooLarge(ValueError):
    """The upload exceeds a size limit. The message is safe to show users."""


@dataclass
class CleanTable:
    name: str
    frame: pd.DataFrame
    source_name: str  # original sheet / table name, for display
    date_columns: set[str] = field(default_factory=set)  # stored as ISO text
    original_names: dict[str, str] = field(default_factory=dict)  # clean name -> header in the file


def safe_identifier(raw: object, fallback: str) -> str:
    """'Order Date (UTC)' -> 'order_date_utc'. Never empty, never starts with a digit, never a keyword."""
    text = unicodedata.normalize("NFKD", str(raw)).encode("ascii", "ignore").decode()
    name = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    if not name or name.startswith("unnamed"):
        name = fallback
    if name[0].isdigit():
        name = f"c_{name}"
    if name in _SQL_RESERVED:
        name = f"{name}_value"
    return name[:60]


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 1
            out.append(n)
    return out


def _non_empty(col: pd.Series) -> pd.Series:
    """Mask of cells that hold a value (not null, not blank text)."""
    return col.notna() & (col.astype(str).str.strip() != "")


SAMPLE = 2000  # values checked first, so obviously non-numeric / non-date columns are skipped fast


def _sample(col: pd.Series, present: pd.Series) -> pd.Series:
    values = col[present]
    return values.sample(SAMPLE, random_state=0) if len(values) > SAMPLE else values


def _try_numeric(col: pd.Series) -> pd.Series | None:
    present = _non_empty(col)
    if not present.any():
        return None
    if len(col) > SAMPLE:  # cheap check on a sample before converting the whole column
        probe = _sample(col, present).astype(str).str.strip().str.replace(_NUMBER_JUNK, "", regex=True)
        if pd.to_numeric(probe, errors="coerce").notna().mean() < CONVERT_THRESHOLD:
            return None
    text = col.astype(str).str.strip().str.replace(_NUMBER_JUNK, "", regex=True)
    text = text.str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # "(1,234)" = accounting negative
    parsed = pd.to_numeric(text, errors="coerce")
    if parsed[present].notna().mean() < CONVERT_THRESHOLD:
        return None
    return parsed.where(present)


def _try_dates(col: pd.Series) -> pd.Series | None:
    present = _non_empty(col)
    if not present.any():
        return None
    if len(col) > SAMPLE:
        probe = _sample(col, present).astype(str).str.strip()
        if probe.str.contains(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}", regex=True).mean() < CONVERT_THRESHOLD:
            return None
    text = col.astype(str).str.strip()
    # Only text that looks like a date (digits with separators); avoids turning codes into dates.
    if text[present].str.contains(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}", regex=True).mean() < CONVERT_THRESHOLD:
        return None
    parsed = pd.to_datetime(text.where(present), errors="coerce", format="mixed")
    if parsed[present].notna().mean() < CONVERT_THRESHOLD:
        return None
    valid = parsed.dropna()
    has_time = bool((valid.dt.normalize() != valid).any())
    return parsed.dt.strftime("%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d").where(parsed.notna())


def _clean_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, set[str], dict[str, str]]:
    """Return the cleaned frame, columns stored as ISO date text, and clean -> original header names."""
    df = df.dropna(how="all").dropna(axis=1, how="all").copy()
    originals = [str(c) for c in df.columns]
    df.columns = _unique([safe_identifier(c, f"column_{i + 1}") for i, c in enumerate(df.columns)])
    renamed = {new: old for new, old in zip(df.columns, originals, strict=True) if new != old}
    dates: set[str] = set()
    for name in df.columns:
        col = df[name]
        if pd.api.types.is_datetime64_any_dtype(col):  # already dates (Excel, Parquet)
            df[name] = col.dt.strftime("%Y-%m-%d").where(col.notna())
            dates.add(name)
            continue
        if not (col.dtype == object or pd.api.types.is_string_dtype(col)):  # pandas 3: text is "str"
            continue
        numeric = _try_numeric(col)
        if numeric is not None:
            df[name] = numeric
            continue
        as_dates = _try_dates(col)
        if as_dates is not None:
            df[name] = as_dates
            dates.add(name)
            continue
        # Mixed objects (lists, dicts from JSON) become text so SQLite can store them.
        df[name] = col.map(lambda v: v if v is None or isinstance(v, (str, int, float)) else str(v))
    return df.reset_index(drop=True), dates, renamed


def clean_tables(raw: list[tuple[str, pd.DataFrame]]) -> list[CleanTable]:
    """Clean every raw table; enforce limits; return SQL-ready tables with unique names."""
    raw = [(n, df) for n, df in raw if df is not None and not df.empty]
    if not raw:
        raise ValueError("no data rows found in the file")
    if len(raw) > MAX_TABLES:
        raise TooLarge(f"the file has {len(raw)} tables; the limit is {MAX_TABLES}")

    total = sum(len(df) for _, df in raw)
    if total > MAX_TOTAL_ROWS:
        raise TooLarge(f"the upload has {total:,} rows in all; the limit is {MAX_TOTAL_ROWS:,}")

    names = _unique([safe_identifier(n, f"table_{i + 1}") for i, (n, _) in enumerate(raw)])
    tables = []
    for name, (source, df) in zip(names, raw, strict=True):
        if len(df.columns) > MAX_COLUMNS:
            raise TooLarge(f"table '{source}' has {len(df.columns)} columns; the limit is {MAX_COLUMNS}")
        if len(df) > MAX_ROWS:
            raise TooLarge(f"table '{source}' has {len(df):,} rows; the limit is {MAX_ROWS:,}")
        frame, dates, renamed = _clean_frame(df)
        if not frame.empty:
            tables.append(
                CleanTable(name=name, frame=frame, source_name=str(source), date_columns=dates, original_names=renamed)
            )
    if not tables:
        raise ValueError("no data rows found in the file")
    return tables
