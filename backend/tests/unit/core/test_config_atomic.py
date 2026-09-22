import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep
from types import SimpleNamespace
from unittest.mock import patch

import tomlkit
from django.test import SimpleTestCase

from apps.core import config as config_module
from apps.core.config import (
    ConfigValidationError,
    update_runtime_application_config,
    write_runtime_config_document,
)


class AtomicRuntimeConfigTests(SimpleTestCase):
    def test_concurrent_application_updates_do_not_lose_independent_changes(self):
        config = self._new_config()
        original_write = config_module.write_runtime_config_document

        def delayed_write(config_object, raw):
            sleep(0.05)
            return original_write(config_object, raw)

        with patch.object(
            config_module,
            "write_runtime_config_document",
            side_effect=delayed_write,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        update_runtime_application_config,
                        config,
                        {"system": {"name": "Concurrent GeoManager"}},
                    ),
                    executor.submit(
                        update_runtime_application_config,
                        config,
                        {"limits": {"upload_max_mb": 512}},
                    ),
                ]
                for future in futures:
                    future.result()

        written = tomlkit.parse(config.config_path.read_text(encoding="utf-8"))
        self.assertEqual(
            written["application"]["system"]["name"],
            "Concurrent GeoManager",
        )
        self.assertEqual(
            written["application"]["limits"]["upload_max_mb"],
            512,
        )

    def test_replace_failure_preserves_original_file_bytes(self):
        config = self._new_config()
        original = config.config_path.read_bytes()
        raw = tomlkit.parse(original.decode("utf-8"))
        raw["application"]["system"]["name"] = "Replacement failure"

        with patch.object(
            config_module.os,
            "replace",
            side_effect=OSError("原子替换失败"),
        ):
            with self.assertRaisesRegex(OSError, "原子替换失败"):
                write_runtime_config_document(config, raw)

        self.assertEqual(config.config_path.read_bytes(), original)

    def test_fsync_failure_preserves_original_file_bytes(self):
        config = self._new_config()
        original = config.config_path.read_bytes()
        raw = tomlkit.parse(original.decode("utf-8"))
        raw["application"]["system"]["name"] = "Fsync failure"

        with patch.object(
            config_module.os,
            "fsync",
            side_effect=OSError("磁盘刷新失败"),
        ):
            with self.assertRaisesRegex(OSError, "磁盘刷新失败"):
                write_runtime_config_document(config, raw)

        self.assertEqual(config.config_path.read_bytes(), original)

    def test_validation_failure_preserves_original_file_bytes(self):
        config = self._new_config()
        original = config.config_path.read_bytes()
        raw = tomlkit.parse(original.decode("utf-8"))
        raw["application"]["system"]["name"] = "Validation failure"

        with patch.object(
            config_module,
            "_load_toml_document",
            side_effect=ConfigValidationError("临时 TOML 验证失败"),
        ):
            with self.assertRaisesRegex(ConfigValidationError, "验证失败"):
                write_runtime_config_document(config, raw)

        self.assertEqual(config.config_path.read_bytes(), original)

    def test_temporary_file_is_in_target_directory_and_result_is_parseable(self):
        config = self._new_config()
        raw = tomlkit.parse(config.config_path.read_text(encoding="utf-8"))
        raw["application"]["system"]["name"] = "Atomic write"
        replacements: list[tuple[Path, Path]] = []
        original_replace = config_module.os.replace

        def capture_replace(source, target):
            replacements.append((Path(source), Path(target)))
            return original_replace(source, target)

        with patch.object(
            config_module.os,
            "replace",
            side_effect=capture_replace,
        ):
            write_runtime_config_document(config, raw)

        self.assertEqual(len(replacements), 1)
        source, target = replacements[0]
        self.assertEqual(source.parent, config.config_path.parent)
        self.assertEqual(target, config.config_path)
        written = tomlkit.parse(config.config_path.read_text(encoding="utf-8"))
        self.assertEqual(written["application"]["system"]["name"], "Atomic write")

    def _new_config(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".toml",
            delete=False,
        ) as output:
            output.write(
                """
[application.system]
name = "GeoManager"
allow_registration = false

[application.limits]
upload_max_mb = 128
query_result_limit = 1000
""".lstrip()
            )
            path = Path(output.name).resolve()
        self.addCleanup(path.unlink, missing_ok=True)
        return SimpleNamespace(config_path=path)
