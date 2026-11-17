"""Read-only process identity; a live worker in another role is not a restart."""

import ctypes
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import uuid

from django.db import connection

_INSTANCE_PID = os.getpid()
_INSTANCE = uuid.uuid4().hex


def _instance():
    global _INSTANCE_PID, _INSTANCE
    if _INSTANCE_PID != os.getpid():
        _INSTANCE_PID = os.getpid()
        _INSTANCE = uuid.uuid4().hex
        _own_started.cache_clear()
    return _INSTANCE


def _started(pid):
    if sys.platform.startswith("linux"):
        text = Path(f"/proc/{pid}/stat").read_text()
        fields = text.rsplit(")", 1)[-1].split()
        if len(fields) < 20:
            raise OSError("Process identity unavailable")
        ticks = fields[19]
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip() + ":" + ticks
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            *[ctypes.POINTER(wintypes.FILETIME)] * 4,
        ]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise OSError(ctypes.get_last_error())
        values = [wintypes.FILETIME() for _ in range(4)]
        try:
            if not kernel.GetProcessTimes(
                handle, *[ctypes.byref(value) for value in values]
            ):
                raise OSError(ctypes.get_last_error())
            return str(values[0].dwHighDateTime << 32 | values[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart="],
        capture_output=True,
        text=True,
        timeout=2,
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode or not result.stdout.strip():
        raise OSError("Process identity unavailable")
    return result.stdout.strip()


@lru_cache(maxsize=8)
def _own_started(pid):
    try:
        return _started(pid)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def database_identity():
    name = str(connection.settings_dict["NAME"])
    if ":memory:" in name or "mode=memory" in name:
        name += f":{os.getpid()}"
    else:
        name = str(Path(name).resolve())
    return hashlib.sha256(name.encode()).hexdigest()


def current_identity():
    pid = os.getpid()
    instance = _instance()
    return {
        "pid": pid,
        "started": _own_started(pid),
        "database": database_identity(),
        "instance": instance,
    }


def alive(identity):
    """True=verified alive, False=verified dead/foreign DB, None=unknown."""
    if not isinstance(identity, dict) or type(identity.get("pid")) is not int:
        return False
    if identity.get("database") != database_identity():
        return False
    pid = identity["pid"]
    if not 0 < pid <= 2147483647:
        return False
    if pid == os.getpid():
        if identity.get("instance") is not None:
            return identity["instance"] == _instance()
        started = _own_started(pid)
        return (
            identity.get("started") == started
            if started is not None and identity.get("started") is not None
            else None
        )
    try:
        started = _started(pid)
        return (
            started == identity["started"]
            if identity.get("started") is not None
            else None
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return None
        return None
