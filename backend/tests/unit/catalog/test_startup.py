from django.test import SimpleTestCase

from apps.catalog.apps import _runserver_autoreload_parent, _server_startup_command


class CatalogStartupScanCommandTests(SimpleTestCase):
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
