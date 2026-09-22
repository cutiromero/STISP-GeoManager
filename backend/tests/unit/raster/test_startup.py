import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import apps.raster as raster_package
import apps.raster.apps as raster_apps
from django.test import SimpleTestCase
from django.test.utils import override_settings

from apps.raster.apps import (
    RasterConfig,
    _runserver_autoreload_parent,
    _server_startup_command,
)


class RasterStartupScanCommandTests(SimpleTestCase):
    def test_server_commands_enable_startup_scan(self):
        self.assertTrue(_server_startup_command(["manage.py", "runserver"]))
        self.assertTrue(
            _server_startup_command(["waitress-serve", "geomanager.wsgi:application"])
        )
        self.assertTrue(_server_startup_command(["uvicorn", "geomanager.asgi:app"]))
        self.assertTrue(_server_startup_command(["daphne", "geomanager.asgi:app"]))

    def test_management_commands_do_not_enable_startup_scan(self):
        self.assertFalse(_server_startup_command(["manage.py", "migrate"]))
        self.assertFalse(_server_startup_command(["manage.py", "collectstatic"]))
        self.assertFalse(_server_startup_command(["manage.py", "test"]))

    def test_runserver_autoreload_parent_is_skipped(self):
        self.assertTrue(_runserver_autoreload_parent(["manage.py", "runserver"], {}))
        self.assertFalse(
            _runserver_autoreload_parent(
                ["manage.py", "runserver"], {"RUN_MAIN": "true"}
            )
        )

    def test_startup_scan_uses_shared_scan_job_submission(self):
        project_config = SimpleNamespace(
            runtime=SimpleNamespace(disable_raster_startup_scan=False)
        )
        config = RasterConfig("apps.raster", raster_package)
        with (
            override_settings(PROJECT_CONFIG=project_config),
            patch.object(raster_apps, "_startup_scan_started", False),
            patch.object(sys, "argv", ["manage.py", "runserver"]),
            patch.dict(os.environ, {"RUN_MAIN": "true"}),
            patch("apps.raster.services.jobs.start_scan_job") as start_scan_job,
            patch("django.db.close_old_connections") as close_old_connections,
            patch("django.db.connection") as startup_connection,
        ):
            config.ready()

        start_scan_job.assert_called_once_with()
        close_old_connections.assert_called_once_with()
        startup_connection.close.assert_called_once_with()
