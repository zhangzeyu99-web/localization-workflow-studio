from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO


UPLOAD_CHUNK_BYTES = 1024 * 1024
DEFAULT_MAX_UPLOAD_MB = 200


class UploadTooLargeError(ValueError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"file too large; max upload size is {max_bytes // (1024 * 1024)} MB")
        self.max_bytes = max_bytes


def max_upload_bytes() -> int:
    raw = os.environ.get("LWS_MAX_UPLOAD_MB", str(DEFAULT_MAX_UPLOAD_MB))
    try:
        mb = max(1, int(raw))
    except ValueError:
        mb = DEFAULT_MAX_UPLOAD_MB
    return mb * 1024 * 1024


def stream_upload(file_obj: BinaryIO, destination: Path, *, max_bytes: int | None = None) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest_builder = hashlib.sha256()
    total_size = 0
    limit = max_bytes or max_upload_bytes()
    try:
        with destination.open("wb") as fh:
            while True:
                chunk = file_obj.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > limit:
                    raise UploadTooLargeError(limit)
                digest_builder.update(chunk)
                fh.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return digest_builder.hexdigest(), total_size
