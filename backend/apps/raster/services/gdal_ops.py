from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any, Callable

from apps.core.cli import popen_cli, run_cli_capture
from apps.core.runtime_config import (
    RuntimeConfigError,
    runtime_symbolizer_timeout_seconds,
)
from apps.raster.services.exceptions import RasterImportError


def gdalinfo_json(path: Path, *, calculate_statistics: bool = False) -> dict[str, Any]:
    command = [
        "gdalinfo",
        "--config",
        "GDAL_PAM_ENABLED",
        "NO",
        "-json",
    ]
    if calculate_statistics:
        command.append("-approx_stats")
    command.append(str(path))
    timeout_seconds = _gdal_timeout_seconds()
    try:
        result = run_cli_capture(command, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RasterImportError(f"gdalinfo 执行超时（{timeout_seconds} 秒）") from exc
    if result.returncode != 0:
        raise RasterImportError(result.stderr.strip() or "gdalinfo 执行失败")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RasterImportError("gdalinfo 未返回有效 JSON") from exc


def run_gdal_command(
    command: list[str],
    progress: Callable[[str], None] | None = None,
    *,
    timeout_seconds: int | None = None,
) -> str:
    timeout_seconds = timeout_seconds or _gdal_timeout_seconds()
    process_options: dict[str, Any] = {}
    if os.name == "nt":
        process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_options["start_new_session"] = True
    process = popen_cli(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **process_options,
    )
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            process.communicate()
        raise RasterImportError(f"GDAL 命令执行超时（{timeout_seconds} 秒）") from exc

    text = output or ""
    if progress and text:
        progress(text)
    if process.returncode != 0:
        raise RasterImportError(text.strip() or f"命令执行失败：{' '.join(command)}")
    return text


def _gdal_timeout_seconds() -> int:
    try:
        return runtime_symbolizer_timeout_seconds()
    except RuntimeConfigError as exc:
        raise RasterImportError(str(exc)) from exc


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except (OSError, ProcessLookupError):
        process.terminate()


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        process.kill()
