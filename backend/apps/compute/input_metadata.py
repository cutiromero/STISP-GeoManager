"""Bounded, authenticated metadata reuse across preflight and submission."""

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

from apps.core.file_evidence import managed_path, read_receipt, write_receipt
from apps.core.storage import app_path
from apps.core.storage_locks import storage_lock, StorageLockTimeout
from .input_versions import source_version
from .packages import ComputeError

# Configuration: fixed slots bound disk use; no access decisions are cached.
CACHE_VERSION = 1
MAX_RECEIPT_BYTES = 1024 * 1024
LOCK_TIMEOUT_SECONDS = 30


def candidate_metadata(resource, options, read):
    # Raster headers are already bounded. Discovering arbitrary VRT dependencies
    # costs as much as reading those headers; keep them on their direct path.
    if resource.data_type not in {"table", "vector"}:
        return read()
    before = source_version(resource)

    def checked_read():
        value = read()
        if source_version(resource) != before:
            raise ComputeError("输入资料在预检期间变化，请重新预检", 409)
        return value

    if managed_path(Path(before["source"]["path"])) is None:
        return checked_read()
    key = hashlib.sha256(
        json.dumps(
            [resource.project_tag_id, resource.pk, options], sort_keys=True
        ).encode()
    ).hexdigest()
    receipt = app_path("cache", "input-metadata", key[:2], key[:3] + ".json")
    identity = {
        "schema": CACHE_VERSION,
        "source": before,
        "options": options,
        "catalog": {
            "name": resource.name,
            "size": resource.size_bytes,
            "crs": resource.coordinate_system,
        },
    }
    with ExitStack() as stack:
        try:
            stack.enter_context(
                storage_lock(
                    app_path("cache", "input-metadata-locks", key[:2] + ".lock"),
                    timeout=LOCK_TIMEOUT_SECONDS,
                )
            )
        except (OSError, StorageLockTimeout):
            return checked_read()
        saved = read_receipt(receipt, "input-metadata-v1", max_bytes=MAX_RECEIPT_BYTES)
        if (
            isinstance(saved, dict)
            and saved.get("identity") == identity
            and isinstance(saved.get("metadata"), dict)
            and source_version(resource) == before
        ):
            return saved["metadata"]
        value = checked_read()
        record = {"identity": identity, "metadata": value}
        if len(json.dumps(record).encode()) < MAX_RECEIPT_BYTES // 2:
            try:
                write_receipt(receipt, record, "input-metadata-v1")
            except OSError:
                pass
        return value
