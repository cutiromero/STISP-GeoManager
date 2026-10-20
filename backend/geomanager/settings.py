from pathlib import Path

from apps.core.cli import configure_runtime_geospatial_environment
from apps.core.config import (
    ConfigValidationError,
    load_project_config,
    metadata_database_path,
    resolve_config_path,
)
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
PROGRAM_ROOT = BASE_DIR.parent
configure_runtime_geospatial_environment()

try:
    CONFIG_PATH = resolve_config_path(PROGRAM_ROOT)
    PROJECT_CONFIG = load_project_config(CONFIG_PATH, program_root=PROGRAM_ROOT)
except ConfigValidationError as exc:
    raise ImproperlyConfigured(str(exc)) from exc


def _get_secret_key() -> str:
    key_file = PROJECT_CONFIG.app_path("database", ".secret_key")
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    from django.core.management.utils import get_random_secret_key

    key = get_random_secret_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key, encoding="utf-8")
    return key


SECRET_KEY = _get_secret_key()
DEBUG = PROJECT_CONFIG.runtime.debug
ALLOWED_HOSTS = list(PROJECT_CONFIG.runtime.allowed_hosts)


def _default_csrf_trusted_origins(allowed_hosts: list[str], debug: bool) -> list[str]:
    origins = {
        origin
        for host in allowed_hosts
        if host != "*"
        for origin in (f"http://{host}", f"https://{host}")
    }
    if debug:
        origins.update(
            {
                "http://127.0.0.1:5173",
                "http://localhost:5173",
            }
        )
    return sorted(origins)


if PROJECT_CONFIG.runtime.csrf_trusted_origins:
    CSRF_TRUSTED_ORIGINS = list(PROJECT_CONFIG.runtime.csrf_trusted_origins)
else:
    CSRF_TRUSTED_ORIGINS = _default_csrf_trusted_origins(ALLOWED_HOSTS, DEBUG)

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.projects",
    "apps.content",
    "apps.knowledge",
    "apps.catalog",
    "apps.raster",
    "apps.standards",
    "apps.ecology",
    "apps.omics",
    "apps.audit",
    "apps.compute",
    "apps.agent",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.FrontendSecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.browser_sessions.BrowserPageSessionMiddleware",
    "apps.projects.middleware.ProjectScopeMiddleware",
    "apps.audit.middleware.UserActivityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "geomanager.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [PROGRAM_ROOT / "frontend" / "dist"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "geomanager.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": metadata_database_path(PROJECT_CONFIG),
        "OPTIONS": {
            "timeout": 30,
            "init_command": "PRAGMA journal_mode=WAL;PRAGMA busy_timeout=30000",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 6},
    },
]

LANGUAGE_CODE = "zh-hans"
LANGUAGES = [
    ("zh-hans", "简体中文"),
    ("en", "English"),
]
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = PROJECT_CONFIG.app_path("static")
FRONTEND_DIST = PROGRAM_ROOT / "frontend" / "dist"
STATICFILES_DIRS = [FRONTEND_DIST] if FRONTEND_DIST.exists() else []
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = PROJECT_CONFIG.app_path("media")
# Keep ordinary JSON/form requests bounded. Multipart file bodies are streamed by
# Django's upload handlers and are validated separately against the runtime limit.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/"
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "apps.core.api.csrf_failure"

LOG_DIR = PROJECT_CONFIG.app_path("logs")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d %(message)s",
        },
    },
    "handlers": {
        "application_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "application.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "standard",
            "encoding": "utf-8",
        },
        "django_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "django.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "standard",
            "encoding": "utf-8",
        },
        "security_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "security.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "standard",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["application_file"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["django_file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["security_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
