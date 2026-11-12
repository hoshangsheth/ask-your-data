"""
Database layer.

    models.py    SQLAlchemy table definitions (the physical schema)
    catalog.py   data dictionary, business glossary, and the schema text sent to the model
    engine.py    engine creation (owner + read-only) and dialect detection
    executor.py  run one query read-only, with a timeout and a row cap
    seed.py      deterministic demo dataset (run: python -m app.db.seed)
"""
