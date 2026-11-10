from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.compute.operator_checks import check_package, source_packages
from apps.compute.packages import ComputeError


class Command(BaseCommand):
    help = "校验算子目录并通过平台运行环境执行包内小样例"

    def add_arguments(self, parser):
        parser.add_argument("directory", type=Path)

    def handle(self, *args, **options):
        try:
            failures = []
            for name, data in source_packages(options["directory"]):
                self.stdout.write("算子：" + name)
                try:
                    check_package(data, emit=self.stdout.write)
                except (ComputeError, OSError, ValueError) as error:
                    self.stdout.write("失败：" + str(error))
                    failures.append(name)
            if failures:
                raise ComputeError("未通过的算子：" + "、".join(failures))
        except (ComputeError, OSError, ValueError) as error:
            raise CommandError(str(error)) from error
