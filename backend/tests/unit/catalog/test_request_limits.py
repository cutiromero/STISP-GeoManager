from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.catalog.views import _json_payload_from_stream


class BoundedJsonStreamTests(SimpleTestCase):
    def test_missing_content_length_cannot_bypass_stream_limit(self):
        request = SimpleNamespace(
            META={"wsgi.input": BytesIO(b"x" * 65)},
        )

        response = _json_payload_from_stream(request, max_body_bytes=64)

        self.assertEqual(response.status_code, 413)
