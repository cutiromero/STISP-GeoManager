"""Import a reviewed, hashed material manifest into one existing project."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

from apps.audit.service import log_operation
from apps.agent.geology_reference import MATERIAL_SOURCE_PREFIX, REFERENCE_SOURCE_PREFIX
from apps.catalog.importer import import_plain_table
from apps.catalog.models import DataResource, ResultArtifact
from apps.catalog.results import _create_result_artifact
from apps.catalog.vector_importer import commit_vector_import
from apps.compute.models import AlgorithmResource
from apps.compute.views import store_version
from apps.core.storage import app_path
from apps.core.display_text import display_text
from apps.projects.context import ProjectScope, is_superadmin, project_scope
from apps.projects.models import Project
from apps.raster.services.importer import import_raster_file

PACKAGE_FILES = ("main.py", "age_logic.py", "operator.yaml", "README.md")


def package(directory):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in PACKAGE_FILES:
            archive.writestr(name, (directory / name).read_bytes())
    return SimpleUploadedFile(directory.name + ".zip", buffer.getvalue())


def verify_version_source(version, directory):
    path = app_path(version.package_path)
    if digest(path) != version.checksum:
        raise CommandError("已登记算法包校验失败")
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != set(PACKAGE_FILES) or any(
            archive.namelist().count(name) != 1
            or archive.read(name) != (directory / name).read_bytes()
            for name in PACKAGE_FILES
        ):
            raise CommandError("算法源码已变化，请登记新版本并保留旧包")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_file(root: Path, item: dict) -> Path:
    relative = Path(item["file"])
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root.resolve()):
        raise CommandError("材料路径须位于导入清单目录内")
    if path.is_symlink() or not path.is_file() or digest(path) != item["sha256"]:
        raise CommandError("材料缺失或内容校验失败：" + str(relative))
    return path


def import_resource(user, root: Path, item: dict):
    item = {
        **item,
        "name": display_text(item["name"]),
        "description": display_text(item["description"]),
        "qualityNote": display_text(item.get("qualityNote", "")),
    }
    path = checked_file(root, item)
    marker = resource_marker(item)
    existing = DataResource.objects.filter(code=item["code"]).first()
    if existing:
        if existing.source != marker or existing.status != "active":
            raise CommandError("同编码资料已变更，请保留并登记新资料：" + item["code"])
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
        resource = DataResource.objects.get(pk=result["resourceId"])
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
        resource = DataResource.objects.get(pk=result["resourceId"])
    elif item["kind"] == "raster":
        dataset = import_raster_file(
            path,
            name=item["name"],
            raster_kind="categorical",
            uploader_id=user.id,
        )
        resource = dataset.data_resource
    else:
        raise CommandError("仅导入已核对的矢量、栅格或表格资料")
    resource.code = item["code"]
    resource.source = marker
    resource.description = item["description"]
    resource.quality_note = item.get("qualityNote", "")
    resource.provider = "地质案例材料"
    resource.save()
    log_operation(
        user,
        "真实地质案例",
        "导入已核对资料",
        "success",
        resource.name,
        target_type="data_resource",
        target_id=resource.id,
        target_name=resource.name,
    )
    return resource


def resource_marker(item):
    reference = item.get("referenceOnly", False)
    if type(reference) is not bool:
        raise CommandError("referenceOnly须为布尔值")
    prefix = REFERENCE_SOURCE_PREFIX if reference else MATERIAL_SOURCE_PREFIX
    return prefix + item["sha256"]


def import_artifact(user, project, root, item, resources):
    item = {
        **item,
        "name": display_text(item["name"]),
        "description": display_text(item["description"]),
    }
    path = checked_file(root, item)
    associated = [resources[key].id for key in item.get("resources", [])]
    existing = list(ResultArtifact.objects.filter(name=item["name"])[:2])
    if existing:
        if (
            len(existing) != 1
            or digest(app_path(existing[0].file_path)) != item["sha256"]
        ):
            raise CommandError("同名成果内容不同，请登记新名称并保留原件")
        artifact = existing[0]
        if set(artifact.related_resources.values_list("id", flat=True)) != set(
            associated
        ):
            raise CommandError("已上传成果的数据关联已变化，请人工核对")
        return artifact
    request = RequestFactory().post(
        "/api/catalog/results/",
        {
            "file": SimpleUploadedFile(path.name, path.read_bytes()),
            "payload": json.dumps(
                {
                    "name": item["name"],
                    "description": item["description"],
                    "provider": "地质案例材料",
                    "sourceType": "direct_import",
                    "resultType": item["resultType"],
                    "categoryCode": item.get("categoryCode", "spatial"),
                    "resourceIds": associated,
                    "accessGroupIds": [],
                    "publish": True,
                },
                ensure_ascii=False,
            ),
        },
    )
    request.user = user
    response = _create_result_artifact(request)
    body = json.loads(response.content)
    if response.status_code != 201:
        raise CommandError(body.get("detail", "成果上传失败"))
    return ResultArtifact.objects.get(pk=body["id"])


class Command(BaseCommand):
    help = "按内容签名幂等导入地质材料、成果和草稿算法；不自动发布算法"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--record", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, **options):
        user = (
            get_user_model()
            .objects.filter(pk=options["user_id"], is_active=True)
            .first()
        )
        if user is None or not is_superadmin(user):
            raise CommandError("导入须指定有效超级管理员")
        project = Project.objects.filter(
            pk=options["project_id"], is_active=True
        ).first()
        if project is None:
            raise CommandError("请指定现有活动的逻辑推理项目")
        manifest_path = Path(options["manifest"]).resolve()
        if manifest_path.stat().st_size > 1_000_000:
            raise CommandError("导入清单过大")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if (
            manifest.get("schemaVersion") != 1
            or not 1 <= len(manifest.get("resources", [])) <= 30
        ):
            raise CommandError("无效材料清单")
        codes = [item["code"] for item in manifest["resources"]]
        if len(set(codes)) != len(codes):
            raise CommandError("材料清单存在重复编码")
        root = manifest_path.parent
        for item in [*manifest["resources"], *manifest.get("artifacts", [])]:
            checked_file(root, item)
        for item in manifest["resources"]:
            resource_marker(item)
        for item in manifest.get("artifacts", []):
            if not set(item.get("resources", [])) <= set(codes):
                raise CommandError("成果关联必须对应清单资料")
        directories = []
        for name in manifest.get("algorithms", []):
            if name not in {"geology-age-check", "geology-age-edit"}:
                raise CommandError("此批次仅允许登记已审阅的时代一致性算法")
            directory = settings.PROGRAM_ROOT / "examples/compute" / name
            package(directory)
            directories.append(directory)
        if options["dry_run"]:
            self.stdout.write(
                f"预检通过：{len(codes)}项资料、{len(manifest.get('artifacts', []))}项成果；无业务写入"
            )
            return
        record = {
            "projectId": project.id,
            "resources": {},
            "artifacts": {},
            "algorithms": {},
        }
        with project_scope(
            ProjectScope((project.id,), project.id, user.id, superadmin=True)
        ):
            resources = {}
            for item in manifest["resources"]:
                resource = import_resource(user, root, item)
                resources[item["code"]] = resource
                record["resources"][item["code"]] = resource.id
            for item in manifest.get("artifacts", []):
                artifact = import_artifact(user, project, root, item, resources)
                record["artifacts"][item["name"]] = artifact.id
            for directory in directories:
                spec = json.loads(
                    (directory / "operator.yaml").read_text(encoding="utf-8")
                )
                algorithm, _ = AlgorithmResource.objects.get_or_create(
                    identifier=spec["identifier"],
                    defaults={
                        "name": spec["name"],
                        "description": spec["description"],
                        "category": "真实地质案例",
                        "author": spec["author"],
                        "created_by": user,
                    },
                )
                version = algorithm.versions.filter(version=spec["version"]).first()
                if version is None:
                    version = store_version(algorithm, package(directory))
                else:
                    verify_version_source(version, directory)
                record["algorithms"][algorithm.identifier] = version.id
        out = Path(options["record"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.stdout.write(
            "真实材料与成果已导入，草稿算法需真实试运行通过后发布；对象清单独立保存。"
        )
