"""Bounded, authenticated file evidence for platform-managed storage only."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile

from django.conf import settings
from django.utils.crypto import constant_time_compare, salted_hmac

from .storage import app_path
from .storage_locks import storage_lock, StorageLockTimeout

# Configuration: fixed slots bound disk use; a collision only evicts a receipt.
SCHEMA = 1
LOCK_TIMEOUT_SECONDS = 30
MAX_RECEIPT_BYTES = 16384


def file_identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
    )


def signature(value, purpose):
    content = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return salted_hmac(
        "platform-file-evidence:" + purpose, content, algorithm="sha256"
    ).hexdigest()


def read_receipt(path, purpose, *, max_bytes=MAX_RECEIPT_BYTES):
    try:
        if path.is_symlink() or path.stat().st_size > max_bytes:
            return None
        with path.open() as stream:
            content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            return None
        envelope = json.loads(content)
        value, authentication = envelope["value"], envelope["authentication"]
        if not isinstance(authentication, str) or not constant_time_compare(
            authentication, signature(value, purpose)
        ):
            return None
        return value
    except (OSError, ValueError, TypeError, KeyError):
        return None


def write_receipt(path, value, purpose):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        {"value": value, "authentication": signature(value, purpose)},
        separators=(",", ":"),
    )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, prefix=".receipt-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def managed_path(path):
    """External paths keep strict full reads; receipts never authorize access."""
    path = Path(path)
    if path.is_symlink():
        return None
    config = settings.PROJECT_CONFIG
    resolved = path.resolve(strict=True)
    for root in (config.app_data, config.research_data_root):
        if resolved.is_relative_to(Path(root).resolve()):
            return resolved
    return None


def cached_digest(path, calculate, *, force=False):
    """Return (digest, reused) after checking current identity on every access."""
    managed = managed_path(path)
    if managed is None:
        return calculate(), False
    key = hashlib.sha256(str(managed).encode()).hexdigest()
    receipt = app_path("cache", "file-evidence", key[:2], key[:3] + ".json")

    def existing():
        current = list(file_identity(managed.stat()))
        value = read_receipt(receipt, "digest-v1")
        if (
            not force
            and isinstance(value, dict)
            and value.get("schema") == SCHEMA
            and value.get("path") == str(managed)
            and value.get("identity") == current
            and isinstance(value.get("sha256"), str)
            and len(value["sha256"]) == 64
            and list(file_identity(managed.stat())) == current
        ):
            return value["sha256"]
        return None

    found = existing()
    if found is not None:
        return found, True
    try:
        # Same slot also shares the lock, including colliding file paths.
        with storage_lock(
            app_path("cache", "file-evidence-locks", key[:2] + ".lock"),
            timeout=LOCK_TIMEOUT_SECONDS,
        ):
            found = existing()
            if found is not None:
                return found, True
            before = list(file_identity(managed.stat()))
            value = calculate()
            if list(file_identity(managed.stat())) == before:
                try:
                    write_receipt(
                        receipt,
                        {
                            "schema": SCHEMA,
                            "path": str(managed),
                            "identity": before,
                            "sha256": value,
                        },
                        "digest-v1",
                    )
                except OSError:
                    pass  # A read-only/full cache must not change file correctness.
            return value, False
    except (OSError, StorageLockTimeout):
        # Failure to coordinate a cache cannot grant trust or block strict reads.
        return calculate(), False


@contextmanager
def artifact_lock(key, *, wait=True):
    with storage_lock(
        app_path("cache", "result-read-locks", key[:2] + ".lock"),
        wait=wait,
        timeout=LOCK_TIMEOUT_SECONDS if wait else None,
    ):
        yield
