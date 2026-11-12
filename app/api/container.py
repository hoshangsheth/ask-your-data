"""
Services container: the long-lived objects one app instance needs, created once and shared by
all requests (stored on `app.state.services`).

    engines     owner + read-only engines for the demo store
    store       where uploaded datasets live: Postgres (one schema each) or local SQLite files
    staging     where upload parts and original files go: Vercel Blob or a local folder
    datasets    upload service (validate -> read -> clean -> profile -> store)
    agent(id)   a SQLAgent per data source ("demo" or an upload id), built lazily and cached

The LLM is built on the first question, so the dashboard and uploads work without an API key.
Tests inject a fake LLM through `Services(settings, llm=FakeLLM(...))`.
"""

import os
import threading
from collections import OrderedDict
from pathlib import Path

from app.agent import SQLAgent
from app.api.rate_limit import RateLimiter
from app.core.config import DATA_ROOT, Settings
from app.datasets.pg_store import PostgresDatasetStore
from app.datasets.service import DatasetService
from app.datasets.staging import BlobStaging, LocalStaging, Staging
from app.datasets.store import DatasetStore, LocalDatasetStore
from app.db.engine import is_postgres, make_engines
from app.llm import LLM, build_llm
from app.sources import DEMO_ID, DataSource, build_demo_source, build_upload_source

MAX_CACHED_AGENTS = 32  # agents hold a schema prompt and an engine; keep the most recent ones


def _local_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else DATA_ROOT / path


class Services:
    def __init__(self, settings: Settings, llm: LLM | None = None):
        self.settings = settings
        self.owner_engine, self.readonly_engine = make_engines(settings.database_url, settings.readonly_database_url)
        self.limiter = RateLimiter(settings.rate_limit_per_minute)
        self.store = self._make_store()
        self.staging = self._make_staging()
        self.datasets = DatasetService(self.store, settings.max_upload_mb)
        self._llm = llm  # injected (tests) or built from settings on first use
        self._demo_source: DataSource | None = None
        self._agents: OrderedDict[str, SQLAgent] = OrderedDict()
        self._lock = threading.Lock()

    # ---- storage backends ----------------------------------------------------------------------
    def _make_store(self) -> DatasetStore:
        if is_postgres(self.settings.database_url):
            return PostgresDatasetStore(self.owner_engine, self.readonly_engine)
        return LocalDatasetStore(_local_path(self.settings.uploads_dir))

    def _make_staging(self) -> Staging:
        s = self.settings
        has_token = bool(s.blob_read_write_token or os.environ.get("BLOB_READ_WRITE_TOKEN"))
        if s.upload_storage == "blob" or (s.upload_storage == "auto" and has_token):
            return BlobStaging(s.blob_read_write_token)
        return LocalStaging(_local_path(s.uploads_dir) / "staging")

    @property
    def storage_info(self) -> dict[str, str]:
        """Which backends are in use (shown by /api/health)."""
        return {
            "datasets": "postgres" if isinstance(self.store, PostgresDatasetStore) else "sqlite-files",
            "files": "vercel-blob" if isinstance(self.staging, BlobStaging) else "local",
        }

    # ---- data sources --------------------------------------------------------------------------
    def source(self, dataset_id: str = DEMO_ID) -> DataSource:
        """The demo store or an uploaded dataset. Raises DatasetNotFound for unknown ids."""
        if dataset_id == DEMO_ID:
            if self._demo_source is None:
                self._demo_source = build_demo_source(self.readonly_engine)
            return self._demo_source
        return build_upload_source(
            self.store.get(dataset_id), self.store.readonly_engine(dataset_id), self.store.schema_for(dataset_id)
        )

    # ---- agents --------------------------------------------------------------------------------
    def _get_llm(self) -> LLM:
        if self._llm is None:
            self._llm = build_llm(self.settings)  # may raise LLMServiceError (e.g. no key)
        return self._llm

    def agent(self, dataset_id: str = DEMO_ID) -> SQLAgent:
        """Agent for a data source, built on first use and cached (least-recently-used eviction)."""
        with self._lock:
            if dataset_id in self._agents:
                self._agents.move_to_end(dataset_id)
                return self._agents[dataset_id]
            s = self.settings
            agent = SQLAgent(
                self._get_llm(),
                self.source(dataset_id),
                max_rows=s.max_rows,
                max_attempts=s.max_attempts,
                timeout_ms=s.query_timeout_ms,
            )
            self._agents[dataset_id] = agent
            while len(self._agents) > MAX_CACHED_AGENTS:
                self._agents.popitem(last=False)
            return agent

    def forget(self, dataset_id: str) -> None:
        """Drop a cached agent (after its dataset is deleted)."""
        with self._lock:
            self._agents.pop(dataset_id, None)

    def dispose(self) -> None:
        """Close connection pools (called on shutdown)."""
        self.owner_engine.dispose()
        self.readonly_engine.dispose()
        self.store.dispose()
