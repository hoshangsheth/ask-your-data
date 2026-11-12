"""
Pieces used by the cloud deployment that can be checked without a cloud: database URL handling,
the per-dataset schema guard in the executor, dialect-specific schema text, and local staging.
"""

import pytest

from app.datasets.pg_store import schema_name
from app.datasets.profile import ColumnProfile, DatasetMeta, TableProfile, schema_text
from app.datasets.staging import LocalStaging, MissingPart
from app.datasets.store import DatasetNotFound
from app.db.engine import is_postgres, normalize_url
from app.db.executor import run_readonly


def test_neon_urls_map_to_psycopg():
    assert normalize_url("postgres://u:p@host/db?sslmode=require") == "postgresql+psycopg://u:p@host/db?sslmode=require"
    assert normalize_url("postgresql://u@h/db") == "postgresql+psycopg://u@h/db"
    assert normalize_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"
    assert normalize_url("sqlite:///./x.db") == "sqlite:///./x.db"
    assert is_postgres("postgres://h/db") and not is_postgres("sqlite:///x.db")


def test_schema_names_come_only_from_valid_ids():
    assert schema_name("3f9a1c2b7d10") == "ds_3f9a1c2b7d10"
    for bad in ("", "demo", "3F9A1C2B7D10", "3f9a1c2b7d10; drop", "../etc"):
        with pytest.raises(DatasetNotFound):
            schema_name(bad)


def test_executor_rejects_unsafe_schema(ro_engine):
    with pytest.raises(ValueError):
        run_readonly(ro_engine, "SELECT 1", max_rows=1, timeout_ms=1000, schema='x"; DROP TABLE orders; --')


def _meta() -> DatasetMeta:
    col = ColumnProfile(name="sold_on", type="DATE", non_null=2, distinct=2, min="2025-01-01", max="2025-02-01")
    return DatasetMeta(
        "abcdefabcdef", "Sales", "sales.csv", "csv", "2026-01-01", 10, [TableProfile("s", "s", 2, [col])]
    )


def test_schema_text_date_hint_follows_dialect():
    assert "strftime" in schema_text(_meta(), "sqlite")
    pg = schema_text(_meta(), "postgres")
    assert "::date" in pg and "strftime" not in pg


def test_meta_without_source_url_still_loads():
    d = _meta().to_dict()
    d.pop("source_url")
    assert DatasetMeta.from_dict(d).source_url == ""


def test_local_staging_round_trip(tmp_path):
    st = LocalStaging(tmp_path)
    uid = "a" * 32
    st.put_part(uid, 1, b"world")
    st.put_part(uid, 0, b"hello ")
    assert st.assemble(uid, 2) == b"hello world"
    with pytest.raises(MissingPart):
        st.assemble(uid, 3)
    st.discard(uid)
    assert not (tmp_path / uid).exists()
    with pytest.raises(MissingPart):
        st.put_part("../../evil", 0, b"x")
    assert st.keep_original(uid, "f.csv", b"x") == ""
