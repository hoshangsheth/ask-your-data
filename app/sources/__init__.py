"""
Data sources: everything the agent needs to answer questions about one dataset.

    base.py     DataSource: read-only engine, allowed tables, schema text, currency, suggestions
    demo.py     the built-in demo store
    upload.py   a user-uploaded dataset

The agent only ever sees a DataSource, so the demo store and uploaded files are handled the same way.
"""

from app.sources.base import DEMO_ID, DataSource
from app.sources.demo import build_demo_source
from app.sources.upload import build_upload_source

__all__ = ["DEMO_ID", "DataSource", "build_demo_source", "build_upload_source"]
