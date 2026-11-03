from pathlib import Path
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from apps.core.views import frontend_app


class FrontendEntryCacheTests(TestCase):
    @override_settings(FRONTEND_DIST=Path("."))
    def test_navigation_does_not_reuse_stale_chunk_manifest(self):
        with patch("pathlib.Path.exists", return_value=True), patch(
            "apps.core.views.render", return_value=HttpResponse("entry")
        ):
            response = frontend_app(RequestFactory().get("/agent/workbench"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response.content, b"entry")
