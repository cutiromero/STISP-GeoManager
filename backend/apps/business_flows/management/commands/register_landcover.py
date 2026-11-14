"""Register the thin operator and its project-owned interpretation flow."""

import io
import hashlib
import json
import zipfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.business_flows.catalog import register_flow, publish_version, require_manager
from apps.business_flows.definitions import normalize_definition, definition_hash
from apps.business_flows.landcover import CODE, definition
from apps.business_flows.models import BusinessFlowDefinition
from apps.compute.models import AlgorithmResource, AlgorithmVersion
from apps.compute.services import submit, publish_algorithm_version
from apps.compute.views import store_version
from apps.projects.access import can_access_project
from apps.projects.context import ProjectScope, project_scope
from apps.projects.features import set_feature
from apps.projects.models import Project, ProjectFeature


class Command(BaseCommand):
    help = "登记地表覆盖算子、试运行和项目业务流，沿用现有权限与不可变版本。"

    def add_arguments(self, parser):
        parser.add_argument("--project", default="gd")
        parser.add_argument("--actor", default="admin")
        parser.add_argument(
            "--stage", choices=["operator", "trial", "publish"], required=True
        )
        parser.add_argument("--resource-id", type=int)
        parser.add_argument("--publish-updates", action="store_true")

    def handle(self, *args, **options):
        project = Project.objects.filter(
            code=options["project"], is_active=True
        ).first()
        actor = (
            get_user_model()
            .objects.filter(username=options["actor"], is_active=True)
            .first()
        )
        if (
            project is None
            or actor is None
            or not can_access_project(actor, project.pk)
        ):
            raise CommandError("项目或登记账号无效")
        with project_scope(ProjectScope((project.pk,), project.pk, actor.pk, True)):
            require_manager(actor)
            source = settings.PROGRAM_ROOT / "examples/compute/landcover-unet"
            declared = json.loads((source / "operator.yaml").read_text())
            algorithm, _ = AlgorithmResource.objects.get_or_create(
                identifier=declared["identifier"],
                defaults={
                    "name": declared["name"],
                    "description": declared["description"],
                    "category": "地表覆盖解译",
                    "created_by": actor,
                },
            )
            version = AlgorithmVersion.objects.filter(
                algorithm=algorithm, version=declared["version"]
            ).first()
            if options["stage"] == "operator":
                stream = io.BytesIO()
                with zipfile.ZipFile(
                    stream, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False
                ) as archive:
                    for path in sorted(source.rglob("*")):
                        if (
                            path.is_file()
                            and "__pycache__" not in path.parts
                            and path.suffix != ".pyc"
                        ):
                            archive.write(path, path.relative_to(source).as_posix())
                if version is None:
                    version = store_version(
                        algorithm,
                        SimpleUploadedFile("landcover.zip", stream.getvalue()),
                    )
                else:
                    from apps.core.storage import app_path

                    with (
                        zipfile.ZipFile(app_path(version.package_path)) as previous,
                        zipfile.ZipFile(io.BytesIO(stream.getvalue())) as current,
                    ):

                        def fingerprints(archive):
                            return {
                                name: hashlib.sha256(archive.read(name)).hexdigest()
                                for name in archive.namelist()
                                if not name.endswith("/")
                            }

                        if fingerprints(previous) != fingerprints(current):
                            raise CommandError("相同版本的代码已变化，请提升算子版本")
                result = {
                    "algorithmId": algorithm.pk,
                    "versionId": version.pk,
                    "status": version.status,
                }
            elif version is None:
                raise CommandError("请先登记算子版本")
            elif options["stage"] == "trial":
                if not options["resource_id"]:
                    raise CommandError("试运行须选择真实原始影像资源")
                task = submit(
                    actor,
                    {
                        "name": "RGB地表解译发布试运行",
                        "versionId": version.pk,
                        "trial": True,
                        "idempotencyKey": "landcover-trial-" + version.checksum[:48],
                        "inputs": {"image": options["resource_id"]},
                        "parameters": {"classes": "all"},
                    },
                )
                result = {
                    "taskId": str(task.pk),
                    "versionId": version.pk,
                    "status": task.status,
                }
            else:
                publish_algorithm_version(actor, version)
                spec = normalize_definition(definition(version.pk))
                flow = (
                    BusinessFlowDefinition.objects.filter(code=CODE)
                    .select_related("current_version")
                    .first()
                )
                if flow is None:
                    flow, published = register_flow(
                        actor,
                        {
                            "code": CODE,
                            "name": "环江油田地表覆盖解译",
                            "description": "选择原始RGB影像，通过五类UNet解译、后处理与配色合成，查看分类地图、面积统计和大屏成果。",
                            "definition": spec,
                        },
                    )
                elif flow.current_version.definition_hash != definition_hash(spec):
                    if not options["publish_updates"]:
                        raise CommandError("业务流已有不同发布版本，请显式选择更新")
                    flow, published = publish_version(actor, flow, spec)
                else:
                    published = flow.current_version
                feature, _ = ProjectFeature.objects.get_or_create(key="ecology_monitor")
                with transaction.atomic():
                    set_feature(
                        actor,
                        feature,
                        project=project,
                        enabled=True,
                        config={
                            "title": "中石油管道 · 地表覆盖解译",
                            "source": "remote_sensing_products",
                            "scenes": ["landcover"],
                            "initialView": {
                                "center": [107.04497, 36.79758],
                                "zoom": 0.3,
                                "regionZoom": 10,
                            },
                        },
                    )
                result = {
                    "flowId": flow.pk,
                    "versionId": published.pk,
                    "version": published.version,
                    "operatorVersionId": version.pk,
                    "projectId": project.pk,
                    "monitorEnabled": True,
                }
        self.stdout.write(json.dumps(result, ensure_ascii=False))
