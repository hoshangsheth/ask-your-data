"""
Dataset profiling: what the model (and the user) is told about an uploaded dataset.

    profile_table(table)        column types, ranges, sample and distinct values (computed once, at upload)
    schema_text(meta)           schema description sent to the model with every question
    suggest_questions(meta)     starter questions shown in the UI (heuristic, no model call)
"""

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from app.datasets.cleaning import CleanTable

MAX_ENUM_VALUES = 15  # list every value for columns with at most this many distinct values
SAMPLE_VALUES = 3


@dataclass
class ColumnProfile:
    name: str
    type: str  # INTEGER | REAL | TEXT | DATE
    non_null: int
    distinct: int
    values: list[Any] = field(default_factory=list)  # all values (low cardinality) or samples
    complete_values: bool = False  # True if `values` lists every distinct value
    min: Any = None
    max: Any = None
    original_name: str = ""  # header as written in the file, e.g. "Revenue ($)" (units live here)


@dataclass
class TableProfile:
    name: str
    source_name: str
    rows: int
    columns: list[ColumnProfile]


@dataclass
class DatasetMeta:
    id: str
    name: str
    filename: str
    file_format: str
    created_at: str
    size_bytes: int
    tables: list[TableProfile]
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "DatasetMeta":
        tables = [TableProfile(**{**t, "columns": [ColumnProfile(**c) for c in t["columns"]]}) for t in d["tables"]]
        return DatasetMeta(**{**d, "tables": tables})


def _py(v: Any) -> Any:
    """numpy scalars -> plain Python, so profiles are JSON-serialisable."""
    return v.item() if hasattr(v, "item") else v


def _profile_column(name: str, col: pd.Series, is_date: bool) -> ColumnProfile:
    present = col.dropna()
    if is_date:
        kind = "DATE"
    elif pd.api.types.is_integer_dtype(col) or (
        pd.api.types.is_float_dtype(col) and not present.empty and (present % 1 == 0).all()
    ):
        kind = "INTEGER"
    elif pd.api.types.is_numeric_dtype(col):
        kind = "REAL"
    else:
        kind = "TEXT"
    distinct = int(present.nunique())
    p = ColumnProfile(name=name, type=kind, non_null=int(len(present)), distinct=distinct)
    if present.empty:
        return p
    if kind in ("INTEGER", "REAL", "DATE"):
        p.min, p.max = _py(present.min()), _py(present.max())
    if distinct <= MAX_ENUM_VALUES and kind != "REAL":
        p.values = sorted((_py(v) for v in present.unique()), key=str)
        p.complete_values = True
    else:
        p.values = [str(_py(v))[:60] for v in present.drop_duplicates().head(SAMPLE_VALUES)]
    return p


def profile_table(table: CleanTable) -> TableProfile:
    cols = [_profile_column(c, table.frame[c], c in table.date_columns) for c in table.frame.columns]
    for c in cols:
        c.original_name = table.original_names.get(c.name, "")
    return TableProfile(name=table.name, source_name=table.source_name, rows=len(table.frame), columns=cols)


def schema_text(meta: DatasetMeta) -> str:
    """Schema description for the SQL prompt (SQLite dialect)."""
    lines = [f'Dataset "{meta.name}" uploaded by the user (file: {meta.filename}).', ""]
    for t in meta.tables:
        origin = f" (from sheet/table '{t.source_name}')" if t.source_name != t.name else ""
        lines.append(f"TABLE {t.name} -- {t.rows:,} rows{origin}")
        for c in t.columns:
            notes = []
            if c.original_name:
                notes.append(f'header in file: "{c.original_name}"')  # keeps units like ($) or (kg)
            if c.min is not None:
                notes.append(f"range {c.min} to {c.max}")
            if c.values:
                label = "Values" if c.complete_values else "Examples"
                notes.append(f"{label}: {', '.join(map(str, c.values))}")
            if c.non_null < t.rows:
                notes.append(f"{t.rows - c.non_null:,} empty")
            lines.append(f"  {c.name} {c.type} -- {'; '.join(notes)}".rstrip(" -"))
        lines.append("")
    lines.append(
        "DATE columns are ISO text 'YYYY-MM-DD' (or 'YYYY-MM-DD HH:MM:SS'): use strftime('%Y-%m', col) "
        "for months and compare with string literals. There are no business definitions for this "
        "dataset: state any assumption (e.g. which column is revenue) in your explanation."
    )
    return "\n".join(lines)


# ---- Starter questions ----------------------------------------------------------------------
def _human(name: str) -> str:
    return name.replace("_", " ")


def _is_id(c: ColumnProfile, rows: int) -> bool:
    return c.name == "id" or c.name.endswith("_id") or (c.type == "INTEGER" and c.distinct == rows and rows > 20)


_MONEY_LIKE = ("revenue", "sales", "amount", "total", "price", "cost", "profit", "value", "spend", "income")


def suggest_questions(meta: DatasetMeta, limit: int = 6) -> list[str]:
    out: list[str] = []
    for t in meta.tables:
        measures = [c for c in t.columns if c.type in ("INTEGER", "REAL") and not _is_id(c, t.rows) and c.distinct > 2]
        # Money-like columns make the most useful first questions ("revenue by store").
        measures.sort(key=lambda c: not any(w in c.name for w in _MONEY_LIKE))
        categories = [c for c in t.columns if c.type == "TEXT" and 2 <= c.distinct <= 30]
        dates = [c for c in t.columns if c.type == "DATE"]
        table = _human(t.name)
        if measures and categories:
            m, g = measures[0], categories[0]
            out.append(f"What is the total {_human(m.name)} by {_human(g.name)}?")
            out.append(f"Which {_human(g.name)} has the highest average {_human(m.name)}?")
        if measures and dates:
            out.append(f"Show the monthly trend of {_human(measures[0].name)}")
        elif dates:
            out.append(f"How many {table} records are there per month?")
        if categories:
            out.append(f"What are the most common {_human(categories[-1].name)} values in {table}?")
        if len(measures) > 1:
            out.append(f"What are the average {_human(measures[0].name)} and {_human(measures[1].name)}?")
        out.append(f"How many rows are in {table}?")
    seen, unique = set(), []
    for q in out:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique[:limit]
