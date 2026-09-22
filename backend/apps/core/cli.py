from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def native_gdal_command(command: list[str], env: dict[str, str]) -> list[str]:
    """Pass Windows GDAL paths as Unicode argv, not the ANSI getenv path.

    All temporary scientific data stays in the TOML application cache.
    """
    executable = Path(command[0]).stem.lower() if command else ""
    if os.name != "nt" or executable not in {
        "gdalinfo",
        "gdalwarp",
        "gdal_translate",
        "gdalbuildvrt",
        "gdaladdo",
    }:
        return command
    options = []
    for name in ("GDAL_DATA", "PROJ_DATA"):
        if env.get(name):
            options.extend(["--config", name, env[name]])
    if not options:
        return command
    from django.conf import settings

    if settings.configured and hasattr(settings, "PROJECT_CONFIG"):
        temporary = settings.PROJECT_CONFIG.app_path("cache", "gdal-tmp")
        temporary.mkdir(parents=True, exist_ok=True)
        options.extend(["--config", "CPL_TMPDIR", str(temporary)])
    return [command[0], *options, *command[1:]]


def runtime_environment_prefix() -> Path | None:
    runtime_prefix = Path(sys.prefix).resolve()
    if (runtime_prefix / "Library" / "bin").is_dir() or (
        runtime_prefix / "bin"
    ).is_dir():
        return runtime_prefix
    return None


def conda_environment_prefix(env: dict[str, str] | None = None) -> Path | None:
    if env is None:
        runtime_prefix = runtime_environment_prefix()
        if runtime_prefix is not None:
            return runtime_prefix

    active_env = os.environ if env is None else env
    configured_prefix = active_env.get("CONDA_PREFIX")
    if configured_prefix:
        prefix = Path(configured_prefix)
        if prefix.exists():
            return prefix

    return None


def pixi_environment_is_active(env: dict[str, str] | None = None) -> bool:
    active_env = os.environ if env is None else env
    return bool(
        active_env.get("PIXI_PROJECT_MANIFEST") or conda_environment_prefix(env)
    )


def cli_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    active_env = dict(os.environ if env is None else env)
    prefix = conda_environment_prefix(env)
    if prefix is None:
        return active_env
    active_env["CONDA_PREFIX"] = str(prefix)

    executable_dirs = [
        prefix / "Library" / "bin",
        prefix / "Scripts",
        prefix / "bin",
    ]
    existing_dirs = [str(path) for path in executable_dirs if path.is_dir()]
    if existing_dirs:
        current_path = active_env.get("PATH", "")
        active_env["PATH"] = os.pathsep.join(
            [*existing_dirs, *([current_path] if current_path else [])]
        )

    for variable, relative_paths in (
        ("GDAL_DATA", (Path("Library/share/gdal"), Path("share/gdal"))),
        ("PROJ_DATA", (Path("Library/share/proj"), Path("share/proj"))),
    ):
        data_directory = next(
            (
                prefix / relative_path
                for relative_path in relative_paths
                if (prefix / relative_path).is_dir()
            ),
            None,
        )
        if data_directory is not None:
            active_env.setdefault(variable, str(data_directory))
    return active_env


def configure_runtime_geospatial_environment() -> None:
    environment = cli_environment()
    if environment.get("PATH"):
        os.environ["PATH"] = environment["PATH"]
    for name in ("GDAL_DATA", "PROJ_DATA"):
        if environment.get(name):
            os.environ.setdefault(name, environment[name])


def resolve_cli_executable(command: list[str], env: dict[str, str]) -> list[str]:
    if not command:
        return command
    executable = Path(command[0])
    if executable.is_absolute() or executable.parent != Path("."):
        return command

    prefix = conda_environment_prefix(env)
    if prefix is None:
        return command
    executable_names = [executable.name]
    if os.name == "nt" and not executable.suffix:
        executable_names.append(f"{executable.name}.exe")
    for directory in (prefix / "Library" / "bin", prefix / "Scripts", prefix / "bin"):
        for name in executable_names:
            candidate = directory / name
            if candidate.is_file():
                return [str(candidate), *command[1:]]
    return command


def build_cli_command(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
) -> list[str]:
    active_env = dict(os.environ if env is None else env)
    prefix = conda_environment_prefix(env)
    if (
        active_env.get("PIXI_PROJECT_MANIFEST")
        or active_env.get("CONDA_PREFIX")
        or prefix
    ):
        if prefix is not None:
            active_env.setdefault("CONDA_PREFIX", str(prefix))
        return resolve_cli_executable(command, active_env)
    return ["pixi", "run", "--executable", *command]


def run_cli_capture(
    command: list[str],
    *,
    cwd: Path = BACKEND_ROOT,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = cli_environment(env)
    return subprocess.run(
        build_cli_command(native_gdal_command(command, process_env), env=process_env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
        env=process_env,
        cwd=cwd,
    )


def popen_cli(
    command: list[str],
    *,
    cwd: Path = BACKEND_ROOT,
    env: dict[str, str] | None = None,
    **kwargs,
) -> subprocess.Popen[str]:
    process_env = cli_environment(env)
    if kwargs.get("text") or kwargs.get("universal_newlines"):
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("errors", "replace")
    return subprocess.Popen(
        build_cli_command(native_gdal_command(command, process_env), env=process_env),
        cwd=cwd,
        env=process_env,
        **kwargs,
    )
