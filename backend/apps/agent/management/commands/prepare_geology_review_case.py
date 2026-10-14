"""Import only reviewed runtime inputs and draft algorithms into an existing project."""

import io
import json
from pathlib import Path
import zipfile

import pandas as pd
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.importer import import_plain_table
from apps.catalog.models import DataResource
from apps.catalog.vector_importer import commit_vector_import
from apps.compute.models import AlgorithmResource
from apps.compute.views import store_version
from apps.core.storage import app_path
from apps.projects.context import ProjectScope, is_superadmin, project_scope
from apps.projects.models import Project
from .prepare_real_geology_case import checked_file, digest

PACKAGE_FILES = ("main.py", "review_logic.py", "operator.yaml", "README.md")
CODES = {"geology-review-initial", "geology-review-coverage", "geology-review-rules"}
ALGORITHMS = {"geology-map-check", "geology-map-correct"}


def package(directory):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in PACKAGE_FILES:
            archive.writestr(name, (directory / name).read_bytes())
    return SimpleUploadedFile(directory.name + ".zip", stream.getvalue())


def verify_source(version, directory):
    path = app_path(version.package_path)
    if digest(path) != version.checksum:
        raise CommandError("已登记算法包校验失败")
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != set(PACKAGE_FILES) or any(
            archive.namelist().count(name) != 1
            or archive.read(name) != (directory / name).read_bytes()
            for name in PACKAGE_FILES
        ):
            raise CommandError("算法源码变化，请增加版本并保留原包")


def import_input(user, root, item):
    path = checked_file(root, item)
    marker = "geology-review-input:" + item["sha256"]
    existing = DataResource.objects.filter(code=item["code"]).first()
    if existing:
        if existing.source != marker or existing.status != "active":
            raise CommandError("现有演示资料已变化，请先核对并保存新版本")
        return existing
    if item["kind"] == "vector":
        result = commit_vector_import(
            SimpleUploadedFile(path.name, path.read_bytes()),
            {
                "name": item["name"],
                "tableName": item["code"].replace("-", "_"),
                "sourceLayerName": item.get("layer", "data"),
                "domainType": "other",
                "categoryCode": "spatial",
                "accessGroupIds": [],
            },
            user,
        )
    elif item["kind"] == "table":
        result = import_plain_table(
            df=pd.read_csv(path, keep_default_na=False, dtype=str),
            name=item["name"],
            table_name=item["code"].replace("-", "_"),
            metadata={},
            source_size_bytes=path.stat().st_size,
            user=user,
            access_group_ids=set(),
            domain_type="other",
            category=None,
        )
    else:
        raise CommandError("本案例只接收已核对的矢量和表格")
    resource = DataResource.objects.get(pk=result["resourceId"])
    resource.code, resource.source = item["code"], marker
    resource.description, resource.provider = (
        item["description"],
        "地质成果检查演示案例",
    )
    resource.save()
    return resource


class Command(BaseCommand):
    help = "导入地质成果检查演示资料与专家知识，登记草稿算法；真实试运行后另行发布"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--record", type=Path, required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, **options):
        user = (
            get_user_model()
            .objects.filter(pk=options["user_id"], is_active=True)
            .first()
        )
        project = Project.objects.filter(
            pk=options["project_id"], is_active=True
        ).first()
        if user is None or not is_superadmin(user) or project is None:
            raise CommandError("请选择现有活动项目及有效超级管理员")
        manifest_path = options["manifest"].resolve()
        if manifest_path.stat().st_size > 100_000:
            raise CommandError("清单超出范围")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        root = manifest_path.parent
        rows = manifest.get("resources", [])
        if (
            manifest.get("schemaVersion") != 1
            or len(rows) != len(CODES)
            or {row["code"] for row in rows} != CODES
            or set(manifest.get("algorithms", [])) != ALGORITHMS
        ):
            raise CommandError("本命令仅接受三项运行资料和两个地质检查算法")
        for row in rows:
            checked_file(root, row)
        from apps.knowledge.management.commands.import_geology_case_knowledge import (
            read_bundle,
        )

        read_bundle(root / "expert_knowledge.json")
        directories = [
            settings.PROGRAM_ROOT / "examples/compute" / name
            for name in sorted(ALGORITHMS)
        ]
        for directory in directories:
            package(directory)
        if options["dry_run"]:
            self.stdout.write(
                "运行资料、知识和草稿包预检通过；内部验收资料不在导入清单"
            )
            return
        record = {"projectId": project.id, "resources": {}, "algorithms": {}}
        with project_scope(ProjectScope((project.id,), project.id, user.id, True)):
            call_command(
                "import_geology_case_knowledge",
                bundle=str(root / "expert_knowledge.json"),
                project_id=project.id,
                user_id=user.id,
                stdout=io.StringIO(),
            )
            for row in rows:
                record["resources"][row["code"]] = import_input(user, root, row).id
            for directory in directories:
                spec = json.loads(
                    (directory / "operator.yaml").read_text(encoding="utf-8")
                )
                algorithm, _ = AlgorithmResource.objects.get_or_create(
                    identifier=spec["identifier"],
                    defaults={
                        "name": spec["name"],
                        "description": spec["description"],
                        "category": "地质成果检查",
                        "author": spec["author"],
                        "created_by": user,
                    },
                )
                version = algorithm.versions.filter(version=spec["version"]).first()
                if version is None:
                    version = store_version(algorithm, package(directory))
                else:
                    verify_source(version, directory)
                record["algorithms"][algorithm.identifier] = version.id
        options["record"].parent.mkdir(parents=True, exist_ok=True)
        options["record"].write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.stdout.write(
            "演示资料与专家知识已导入；算法保持草稿，需通过真实试运行后发布"
        )
