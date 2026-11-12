"""
Upload staging: where the parts of a file wait until the upload is complete, and where the
original file is kept afterwards.

Browsers send a file in parts of a few MB (a Vercel request body is capped at 4.5 MB), so a
50 MB upload is ~13 small requests. Each part is stored here; the final request joins them,
parses the file and (in the cloud) keeps the original next to the dataset.

    staging.put_part(upload_id, index, data)
    data = staging.assemble(upload_id, parts)        # raises MissingPart
    url = staging.keep_original(upload_id, filename, data)   # "" when originals aren't kept
    staging.discard(upload_id); staging.delete_original(url)

LocalStaging   parts in a temp folder; originals not kept (the SQLite file is the dataset)
BlobStaging    parts and originals in a private Vercel Blob store
"""

import os
import re
import shutil
from pathlib import Path
from typing import Protocol

_UPLOAD_ID = re.compile(r"^[a-f0-9]{32}$")
MAX_PARTS = 1000


class MissingPart(ValueError):
    pass


def check_upload_id(upload_id: str) -> str:
    if not _UPLOAD_ID.match(upload_id or ""):
        raise MissingPart("unknown upload")
    return upload_id


def _safe_filename(name: str) -> str:
    """Keep blob pathnames boring: letters, digits, dot, dash, underscore."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._")
    return cleaned[:100] or "file"


class Staging(Protocol):
    def put_part(self, upload_id: str, index: int, data: bytes) -> None: ...
    def assemble(self, upload_id: str, parts: int) -> bytes: ...
    def discard(self, upload_id: str) -> None: ...
    def keep_original(self, upload_id: str, filename: str, data: bytes) -> str: ...
    def delete_original(self, url: str) -> None: ...


class LocalStaging:
    def __init__(self, root: Path):
        self.root = root

    def _dir(self, upload_id: str) -> Path:
        return self.root / check_upload_id(upload_id)

    def put_part(self, upload_id: str, index: int, data: bytes) -> None:
        folder = self._dir(upload_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{index:05d}.part").write_bytes(data)

    def assemble(self, upload_id: str, parts: int) -> bytes:
        folder = self._dir(upload_id)
        chunks = []
        for i in range(parts):
            p = folder / f"{i:05d}.part"
            if not p.exists():
                raise MissingPart(f"part {i + 1} of {parts} is missing; upload the file again")
            chunks.append(p.read_bytes())
        return b"".join(chunks)

    def discard(self, upload_id: str) -> None:
        shutil.rmtree(self._dir(upload_id), ignore_errors=True)

    def keep_original(self, upload_id: str, filename: str, data: bytes) -> str:
        return ""

    def delete_original(self, url: str) -> None:
        pass


class BlobStaging:
    """Vercel Blob (private store). Credentials: BLOB_READ_WRITE_TOKEN, set when a store is connected."""

    def __init__(self, token: str = ""):
        if token and not os.environ.get("BLOB_READ_WRITE_TOKEN"):
            os.environ["BLOB_READ_WRITE_TOKEN"] = token  # the SDK reads it from the environment
        from vercel.blob import sync as blob  # imported lazily: only needed in the cloud

        self.blob = blob

    @staticmethod
    def _part_path(upload_id: str, index: int) -> str:
        return f"staging/{check_upload_id(upload_id)}/{index:05d}.part"

    def put_part(self, upload_id: str, index: int, data: bytes) -> None:
        self.blob.put_blob(self._part_path(upload_id, index), data, access="private", allow_overwrite=True)

    def assemble(self, upload_id: str, parts: int) -> bytes:
        chunks = []
        for i in range(parts):
            try:
                chunks.append(self.blob.get_blob(self._part_path(upload_id, i), access="private").body)
            except self.blob.BlobNotFoundError as e:
                raise MissingPart(f"part {i + 1} of {parts} is missing; upload the file again") from e
        return b"".join(chunks)

    def discard(self, upload_id: str) -> None:
        paths = [b.pathname for b in self.blob.query_blobs(prefix=f"staging/{check_upload_id(upload_id)}/")]
        if paths:
            self.blob.delete_blob(paths)

    def keep_original(self, upload_id: str, filename: str, data: bytes) -> str:
        result = self.blob.put_blob(
            f"originals/{check_upload_id(upload_id)}/{_safe_filename(filename)}",
            data,
            access="private",
            allow_overwrite=True,
        )
        return result.url

    def delete_original(self, url: str) -> None:
        if url:
            self.blob.delete_blob(url)
