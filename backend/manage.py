#!/usr/bin/env python
import os
import sys
from pathlib import Path


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geomanager.settings")
    program_root = Path(__file__).resolve().parent.parent
    from apps.core.config import persist_config_argument

    persist_config_argument(sys.argv, program_root)
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
