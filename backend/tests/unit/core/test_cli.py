from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from apps.core import cli


class CliCommandTests(SimpleTestCase):
    def test_default_mode_wraps_command_when_pixi_environment_is_not_active(self):
        self.assertEqual(
            cli.build_cli_command(
                ["gdalwarp", "-t_srs", "EPSG:3857"],
                env={},
            ),
            ["pixi", "run", "--executable", "gdalwarp", "-t_srs", "EPSG:3857"],
        )

    def test_active_pixi_environment_runs_command_directly(self):
        self.assertEqual(
            cli.build_cli_command(
                ["gdalinfo", "-json", "a.tif"],
                env={"PIXI_PROJECT_MANIFEST": "/opt/app/backend/pixi.toml"},
            ),
            ["gdalinfo", "-json", "a.tif"],
        )

    def test_conda_prefix_marks_pixi_environment_active(self):
        self.assertEqual(
            cli.build_cli_command(
                ["gdalinfo"],
                env={"CONDA_PREFIX": "/opt/app/backend/.pixi/envs/default"},
            ),
            ["gdalinfo"],
        )

    def test_conda_environment_resolves_gdal_and_sets_runtime_variables(self):
        with tempfile.TemporaryDirectory() as tempdir:
            prefix = Path(tempdir)
            executable = prefix / "Library" / "bin" / "gdalinfo.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            gdal_data = prefix / "Library" / "share" / "gdal"
            gdal_data.mkdir(parents=True)
            proj_data = prefix / "Library" / "share" / "proj"
            proj_data.mkdir(parents=True)

            environment = cli.cli_environment({"CONDA_PREFIX": str(prefix)})
            command = cli.build_cli_command(["gdalinfo", "-json"], env=environment)

        self.assertEqual(command[0], str(executable))
        self.assertEqual(command[1:], ["-json"])
        self.assertEqual(environment["GDAL_DATA"], str(gdal_data))
        self.assertEqual(environment["PROJ_DATA"], str(proj_data))
        self.assertIn(str(executable.parent), environment["PATH"])

    def test_linux_conda_layout_resolves_gdal_data_and_executable(self):
        with tempfile.TemporaryDirectory() as tempdir:
            prefix = Path(tempdir)
            executable = prefix / "bin" / "gdalinfo"
            executable.parent.mkdir(parents=True)
            executable.touch()
            gdal_data = prefix / "share" / "gdal"
            gdal_data.mkdir(parents=True)
            proj_data = prefix / "share" / "proj"
            proj_data.mkdir(parents=True)

            environment = cli.cli_environment({"CONDA_PREFIX": str(prefix)})
            command = cli.build_cli_command(["gdalinfo", "-json"], env=environment)

        self.assertEqual(command[0], str(executable))
        self.assertEqual(environment["GDAL_DATA"], str(gdal_data))
        self.assertEqual(environment["PROJ_DATA"], str(proj_data))

    def test_running_python_environment_wins_over_stale_conda_prefix(self):
        with tempfile.TemporaryDirectory() as tempdir:
            # Windows TEMP may use an 8.3 alias; sys.prefix is resolved by the CLI.
            root = Path(tempdir).resolve()
            runtime_prefix = root / "geomanager"
            stale_prefix = root / "base"
            executable = runtime_prefix / "Library" / "bin" / "gdalinfo.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            stale_prefix.mkdir()

            with (
                mock.patch.object(cli.sys, "prefix", str(runtime_prefix)),
                mock.patch.dict(
                    cli.os.environ,
                    {"CONDA_PREFIX": str(stale_prefix), "PATH": ""},
                    clear=True,
                ),
            ):
                environment = cli.cli_environment()
                command = cli.build_cli_command(
                    ["gdalinfo", "-json"], env=environment
                )

        self.assertEqual(environment["CONDA_PREFIX"], str(runtime_prefix))
        self.assertEqual(command[0], str(executable))

    def test_run_cli_capture_uses_backend_workspace(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with mock.patch.object(cli.subprocess, "run", return_value=result) as run:
            self.assertIs(cli.run_cli_capture(["gdalinfo"], env={}), result)

        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0], ["pixi", "run", "--executable", "gdalinfo"]
        )
        self.assertEqual(run.call_args.kwargs["cwd"], cli.BACKEND_ROOT)
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_popen_cli_uses_backend_workspace(self):
        process = mock.Mock()
        with mock.patch.object(cli.subprocess, "Popen", return_value=process) as popen:
            self.assertIs(
                cli.popen_cli(["gdalwarp"], stdout=subprocess.PIPE, env={}), process
            )

        popen.assert_called_once()
        self.assertEqual(
            popen.call_args.args[0], ["pixi", "run", "--executable", "gdalwarp"]
        )
        self.assertEqual(popen.call_args.kwargs["cwd"], cli.BACKEND_ROOT)
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.PIPE)
