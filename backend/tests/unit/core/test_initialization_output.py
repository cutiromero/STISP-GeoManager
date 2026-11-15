from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core.initialization import print_superadmin_credentials_on_startup


class StartupCredentialOutputTests(SimpleTestCase):
    def test_startup_does_not_read_or_print_the_initial_password(self):
        with (
            patch(
                "apps.core.initialization._server_startup_command", return_value=True
            ),
            patch(
                "apps.core.initialization.ensure_superadmin_defaults",
                return_value=(SimpleNamespace(get_username=lambda: "admin"), None),
            ),
            patch(
                "apps.core.initialization._initial_password",
                side_effect=AssertionError("must not read credentials"),
            ) as read,
            patch("builtins.print") as output,
        ):
            print_superadmin_credentials_on_startup()
        read.assert_not_called()
        message = output.call_args.args[0]
        self.assertIn("admin", message)
        self.assertNotIn("密码:", message)
