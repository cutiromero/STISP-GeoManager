from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import tempfile

from apps.core.config import APP_SUBDIRS, RESEARCH_SUBDIRS, metadata_database_path

from .settings import *  # noqa: F403


TEST_DATA_ROOT = Path(tempfile.gettempdir()) / f"geomanager-tests-{os.getpid()}"
PROJECT_CONFIG = replace(  # noqa: F405
    PROJECT_CONFIG,  # noqa: F405
    app_data=TEST_DATA_ROOT / "appdata",
    research_data_root=TEST_DATA_ROOT / "research",
)

for subdir in APP_SUBDIRS:
    PROJECT_CONFIG.app_path(subdir).mkdir(parents=True, exist_ok=True)
for subdir in RESEARCH_SUBDIRS:
    PROJECT_CONFIG.research_path(subdir).mkdir(parents=True, exist_ok=True)

DATABASES["default"]["NAME"] = metadata_database_path(PROJECT_CONFIG)  # noqa: F405
STATIC_ROOT = PROJECT_CONFIG.app_path("static")
MEDIA_ROOT = PROJECT_CONFIG.app_path("media")
LOG_DIR = PROJECT_CONFIG.app_path("logs")
LOGGING["handlers"]["application_file"]["filename"] = LOG_DIR / "application.log"  # noqa: F405
LOGGING["handlers"]["django_file"]["filename"] = LOG_DIR / "django.log"  # noqa: F405
LOGGING["handlers"]["security_file"]["filename"] = LOG_DIR / "security.log"  # noqa: F405
