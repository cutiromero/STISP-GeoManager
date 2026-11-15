"""Register the actual three-season RF operator and its project-owned flow."""

import hashlib
import io
import json
import zipfile
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from apps.business_flows.catalog import register_flow, publish_version, require_manager
from apps.business_flows.definitions import normalize_definition, definition_hash
from apps.business_flows.models import BusinessFlowDefinition
from apps.business_flows.spartina import CODE, definition
from apps.compute.models import AlgorithmResource, AlgorithmVersion
from apps.compute.services import submit, publish_algorithm_version
from apps.compute.views import store_version
from apps.core.storage import app_path
from apps.projects.access import can_access_project
from apps.projects.context import ProjectScope, project_scope
from apps.projects.features import set_feature
from apps.projects.models import Project, ProjectFeature

# CONFIGURATION
DEFAULT_INPUTS = {}
DEFAULT_REGION = {}


class Command(BaseCommand):
    source_folder = "spartina-rf"
    flow_code = CODE
    flow_title = "互花米草分布解译"
    flow_description = "选择研究区，以三季节48特征RF解译互花米草，生成分类、概率和面积统计，在监测大屏查看。"
    algorithm_category = "互花米草分布解译"
    scene = "spartina"
    default_inputs = DEFAULT_INPUTS
    default_parameters = DEFAULT_REGION
    build_definition = staticmethod(definition)
    help = "登记互花米草RF算子、真实试运行及项目专属业务流"

    def trial_key(self, checksum, inputs, parameters):
        signature = hashlib.sha256(
            json.dumps(
                {"checksum": checksum, "inputs": inputs, "parameters": parameters},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return "trial-" + self.source_folder + "-" + signature[:48]

    def add_arguments(self, parser):
        parser.add_argument("--project", default="06")
        parser.add_argument("--actor", default="admin")
        parser.add_argument(
            "--stage", choices=["operator", "trial", "publish"], required=True
        )
        parser.add_argument("--inputs-json", default=json.dumps(self.default_inputs))
        parser.add_argument(
            "--parameters-json", default=json.dumps(self.default_parameters)
        )
        parser.add_argument("--publish-updates", action="store_true")

    def handle(self, *args, **options):
        project = Project.objects.get(code=options["project"], is_active=True)
        actor = get_user_model().objects.get(username=options["actor"], is_active=True)
        if not can_access_project(actor, project.pk):
            raise CommandError("登记账号无项目权限")
        with project_scope(ProjectScope((project.pk,), project.pk, actor.pk, True)):
            require_manager(actor)
            source = settings.PROGRAM_ROOT / "examples/compute" / self.source_folder
            declared = json.loads((source / "operator.yaml").read_text())
            algorithm, _ = AlgorithmResource.objects.get_or_create(
                identifier=declared["identifier"],
                defaults={
                    "name": declared["name"],
                    "description": declared["description"],
                    "category": self.algorithm_category,
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
                        SimpleUploadedFile(
                            self.source_folder + ".zip", stream.getvalue()
                        ),
                    )
                else:

                    def contents(archive):
                        return {
                            name: hashlib.sha256(archive.read(name)).hexdigest()
                            for name in archive.namelist()
                            if not name.endswith("/")
                        }

                    with (
                        zipfile.ZipFile(app_path(version.package_path)) as previous,
                        zipfile.ZipFile(io.BytesIO(stream.getvalue())) as current,
                    ):
                        if contents(previous) != contents(current):
                            raise CommandError("相同版本内容已变化，请提升算子版本")
                result = {
                    "algorithmId": algorithm.pk,
                    "versionId": version.pk,
                    "status": version.status,
                }
            elif version is None:
                raise CommandError("请先登记算子")
            elif options["stage"] == "trial":
                inputs = json.loads(options["inputs_json"])
                parameters = json.loads(options["parameters_json"])
                if not inputs:
                    raise CommandError("试运行须显式指定已登记原始资料 --inputs-json")
                if not parameters:
                    raise CommandError("试运行须显式指定研究区与时期 --parameters-json")
                task = submit(
                    actor,
                    {
                        "name": self.flow_title + "发布试运行",
                        "versionId": version.pk,
                        "trial": True,
                        "idempotencyKey": self.trial_key(
                            version.checksum, inputs, parameters
                        ),
                        "inputs": inputs,
                        "parameters": parameters,
                    },
                )
                result = {
                    "taskId": str(task.pk),
                    "versionId": version.pk,
                    "status": task.status,
                }
            else:
                publish_algorithm_version(actor, version)
                spec = normalize_definition(self.build_definition(version.pk))
                flow = (
                    BusinessFlowDefinition.objects.filter(code=self.flow_code)
                    .select_related("current_version")
                    .first()
                )
                if flow is None:
                    flow, published = register_flow(
                        actor,
                        {
                            "code": self.flow_code,
                            "name": self.flow_title,
                            "description": self.flow_description,
                            "definition": spec,
                        },
                    )
                elif (
                    flow.current_version is None
                    or flow.current_version.definition_hash != definition_hash(spec)
                ):
                    if not options["publish_updates"]:
                        raise CommandError("业务流已有不同版本，请显式更新")
                    flow, published = publish_version(actor, flow, spec)
                else:
                    published = flow.current_version
                feature, _ = ProjectFeature.objects.get_or_create(key="ecology_monitor")
                existing = project.feature_settings.filter(feature=feature).first()
                config = dict(existing.config or {}) if existing else {}
                config.setdefault("title", "生态遥感监测 · 互花米草与野火")
                config.setdefault(
                    "initialView",
                    {"center": [121.92, 31.24], "zoom": 0.3, "regionZoom": 11.5},
                )
                config["source"] = "remote_sensing_products"
                config["scenes"] = list(
                    dict.fromkeys([*config.get("scenes", []), self.scene])
                )
                set_feature(
                    actor, feature, project=project, enabled=True, config=config
                )
                result = {
                    "flowId": flow.pk,
                    "versionId": published.pk,
                    "version": published.version,
                    "operatorVersionId": version.pk,
                    "projectId": project.pk,
                }
        self.stdout.write(json.dumps(result, ensure_ascii=False))
