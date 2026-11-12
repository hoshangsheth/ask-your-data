"""
User-uploaded datasets: turn a file into SQL tables the agent can query.

Pipeline (one module per step):
    formats.py   read a file (CSV, Excel, JSON, Parquet, PDF, Word, ...) into raw tables
    cleaning.py  make tables SQL-friendly: safe names, typed columns, size limits
    store.py     persist tables + metadata (local: one read-only SQLite file per dataset)
    profile.py   describe a dataset for the model and suggest starter questions
    service.py   orchestrates the steps for an upload: validate -> parse -> clean -> store

Usage:
    from app.datasets.service import DatasetService
    info = service.ingest(file_bytes, "sales.xlsx")
"""
