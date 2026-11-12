"""
Upload orchestration: validate -> read -> clean -> profile -> store.

Usage:
    service = DatasetService(store, max_upload_mb=50)
    meta = service.ingest(data, "Q3 sales.xlsx")      # raises UploadError with a user-safe message
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.datasets.cleaning import TooLarge, clean_tables
from app.datasets.formats import SUPPORTED_EXTENSIONS, UnreadableFile, UnsupportedFile, read_tables
from app.datasets.profile import DatasetMeta, profile_table, suggest_questions
from app.datasets.store import LocalDatasetStore


class UploadError(ValueError):
    """The upload was rejected. `status_code` is the HTTP status to return; message is user-safe."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class DatasetService:
    def __init__(self, store: LocalDatasetStore, max_upload_mb: int = 50):
        self.store = store
        self.max_bytes = max_upload_mb * 1024 * 1024

    @staticmethod
    def supported_extensions() -> tuple[str, ...]:
        return SUPPORTED_EXTENSIONS

    def ingest(self, data: bytes, filename: str) -> DatasetMeta:
        # 1) Validate size and type before doing any parsing work.
        if not data:
            raise UploadError("the file is empty")
        if len(data) > self.max_bytes:
            raise UploadError(f"the file is larger than {self.max_bytes // (1024 * 1024)} MB", status_code=413)
        filename = Path(filename or "data").name  # drop any client-supplied directories

        # 2) Read and clean into SQL-ready tables.
        try:
            tables = clean_tables(read_tables(data, filename))
        except UnsupportedFile as e:
            raise UploadError(str(e), status_code=415) from e
        except TooLarge as e:
            raise UploadError(str(e), status_code=413) from e
        except (UnreadableFile, ValueError) as e:
            raise UploadError(str(e), status_code=422) from e

        # 3) Profile, then store tables + metadata.
        meta = DatasetMeta(
            id=uuid.uuid4().hex[:12],
            name=Path(filename).stem or "Uploaded data",
            filename=filename,
            file_format=Path(filename).suffix.lower().lstrip("."),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            size_bytes=len(data),
            tables=[profile_table(t) for t in tables],
        )
        meta.suggestions = suggest_questions(meta)
        self.store.save(meta, tables)
        return meta
