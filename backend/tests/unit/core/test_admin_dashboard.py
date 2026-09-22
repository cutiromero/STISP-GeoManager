from django.test import SimpleTestCase

from apps.core import admin_api


class LoadAverageTests(SimpleTestCase):
    def test_returns_zeroes_when_platform_has_no_load_average(self):
        original = getattr(admin_api.os, "getloadavg", None)
        if original is not None:
            delattr(admin_api.os, "getloadavg")
        try:
            self.assertEqual(admin_api._load_average(), [0.0, 0.0, 0.0])
        finally:
            if original is not None:
                admin_api.os.getloadavg = original
