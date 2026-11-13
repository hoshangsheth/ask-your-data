"""
Zip uploads (app/datasets/formats.py): every data file inside becomes a table, junk is skipped,
and archives that are too big, too many or unreadable fail with a clear message.
"""

import pytest

from app.datasets import formats
from app.datasets.cleaning import clean_tables
from app.datasets.formats import TooManyFiles, UnreadableFile, read_tables
from tests import sample_files as files


def test_each_file_in_the_zip_becomes_a_table():
    tables = clean_tables(read_tables(files.relational_zip(), "shop.zip"))
    assert sorted(t.name for t in tables) == ["customers", "orders"]  # readme, __MACOSX and .DS_Store skipped
    orders = next(t for t in tables if t.name == "orders")
    assert len(orders.frame) == 4 and orders.frame["amount"].sum() == 470


def test_mixed_formats_and_sheets_in_one_zip():
    raw = read_tables(
        files.zip_of({"a.csv": files.csv(), "b.xlsx": files.xlsx(), "c.json": files.json_records()}), "x.zip"
    )
    assert len(raw) >= 3 and {"a", "c"} <= {name for name, _ in raw}


def test_same_file_name_in_two_folders_gets_unique_table_names():
    data = files.zip_of({"2023/sales.csv": files.csv(), "2024/sales.csv": files.csv()})
    assert sorted(t.name for t in clean_tables(read_tables(data, "years.zip"))) == ["sales", "sales_2"]


@pytest.mark.parametrize(
    "data, message",
    [
        (b"PK\x03\x04 not really a zip", "not a valid zip"),
        (files.zip_of({"notes.md": b"hello"}), "no supported data files"),
        (files.zip_of({"bad.json": b"{oops"}), "bad.json: invalid JSON"),
    ],
)
def test_unreadable_zips(data, message):
    with pytest.raises(UnreadableFile, match=message):
        read_tables(data, "x.zip")


def test_too_many_files(monkeypatch):
    monkeypatch.setattr(formats, "MAX_ZIP_FILES", 2)
    with pytest.raises(TooManyFiles, match="3 data files"):
        read_tables(files.zip_of({f"t{i}.csv": files.csv() for i in range(3)}), "x.zip")


def test_zip_bomb_is_stopped(monkeypatch):
    monkeypatch.setattr(formats, "MAX_UNZIPPED_BYTES", 10_000)
    bomb = files.zip_of({"big.csv": b"a,b\n" + b"1,2\n" * 50_000})  # 200 KB that compresses to ~1 KB
    assert len(bomb) < 10_000
    with pytest.raises(TooManyFiles, match="larger than"):
        read_tables(bomb, "bomb.zip")
