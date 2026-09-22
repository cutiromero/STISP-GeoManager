from pathlib import Path

from django.test import SimpleTestCase


class DockerEntrypointTests(SimpleTestCase):
    def test_waitress_upload_limit_has_one_gib_headroom_and_bounded_timeout(self):
        repository_root = Path(__file__).resolve().parents[4]
        entrypoint = repository_root.joinpath("docker", "entrypoint.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("--max-request-body-size=1207959552", entrypoint)
        self.assertIn("--channel-timeout=720", entrypoint)
