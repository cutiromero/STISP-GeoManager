from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from apps.raster.services import gdal_ops
from apps.raster.services.exceptions import RasterImportError


class GdalOpsTests(SimpleTestCase):
    def test_gdalinfo_uses_cli_wrapper(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"size":[1,1]}',
            stderr="",
        )
        with (
            mock.patch.object(gdal_ops, "_gdal_timeout_seconds", return_value=120),
            mock.patch.object(gdal_ops, "run_cli_capture", return_value=result) as run,
        ):
            self.assertEqual(gdal_ops.gdalinfo_json(Path("a.tif")), {"size": [1, 1]})

        run.assert_called_once_with(
            [
                "gdalinfo",
                "--config",
                "GDAL_PAM_ENABLED",
                "NO",
                "-json",
                "a.tif",
            ],
            timeout=120,
        )

    def test_gdalinfo_can_request_approximate_statistics(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"size":[1,1]}',
            stderr="",
        )
        with (
            mock.patch.object(gdal_ops, "_gdal_timeout_seconds", return_value=120),
            mock.patch.object(gdal_ops, "run_cli_capture", return_value=result) as run,
        ):
            gdal_ops.gdalinfo_json(Path("a.tif"), calculate_statistics=True)

        run.assert_called_once_with(
            [
                "gdalinfo",
                "--config",
                "GDAL_PAM_ENABLED",
                "NO",
                "-json",
                "-approx_stats",
                "a.tif",
            ],
            timeout=120,
        )

    def test_gdal_command_uses_cli_wrapper(self):
        process = mock.Mock()
        process.communicate.return_value = ("", None)
        process.returncode = 0
        with (
            mock.patch.object(gdal_ops, "_gdal_timeout_seconds", return_value=120),
            mock.patch.object(gdal_ops, "popen_cli", return_value=process) as popen,
        ):
            gdal_ops.run_gdal_command(["gdalwarp", "in.tif", "out.tif"])

        popen.assert_called_once()
        self.assertEqual(
            popen.call_args.args[0],
            ["gdalwarp", "in.tif", "out.tif"],
        )
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.STDOUT)
        process.communicate.assert_called_once_with(timeout=120)

    def test_gdal_command_terminates_process_after_timeout(self):
        process = mock.Mock()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired("gdalwarp", 3),
            ("partial output", None),
        ]
        with (
            mock.patch.object(gdal_ops, "popen_cli", return_value=process),
            mock.patch.object(gdal_ops, "_terminate_process_tree") as terminate,
        ):
            with self.assertRaisesMessage(RasterImportError, "执行超时"):
                gdal_ops.run_gdal_command(
                    ["gdalwarp", "in.tif", "out.tif"], timeout_seconds=3
                )

        terminate.assert_called_once_with(process)

    def test_gdalinfo_raises_import_error_on_command_failure(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="failed",
        )
        with (
            mock.patch.object(gdal_ops, "_gdal_timeout_seconds", return_value=120),
            mock.patch.object(gdal_ops, "run_cli_capture", return_value=result),
        ):
            with self.assertRaisesMessage(RasterImportError, "failed"):
                gdal_ops.gdalinfo_json(Path("a.tif"))
