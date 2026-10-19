"""Idempotent local Demo setup; scientific assets stay outside Git."""

import importlib.util
import io
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from apps.agent.models import AgentPolicy
from apps.agent.policy import default_policy
from apps.catalog.importer import import_plain_table
from apps.catalog.models import DataResource, VectorDataset
from apps.catalog.services import upsert_vector_catalog_record
from apps.catalog.vector_importer import commit_vector_import, frame_summary
from apps.compute.models import AlgorithmResource, AlgorithmVersion
from apps.compute.packages import checksum
from apps.compute.views import store_version
from apps.core.storage import app_path, vector_geopackage_path
from apps.core.initialization import is_superadmin_user
from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import serialize
from apps.projects.context import ProjectScope, project_scope
from apps.projects.models import Project, ProjectMembership
from apps.raster.services.importer import import_raster_file

ALGORITHMS = [
    "raster-ndvi",
    "vector-geometry-repair",
    "ndvi-change-candidates",
    "ecology-investigation-priority",
    "geology-check",
    "geology-edit",
]
PACKAGE_FILES = ("main.py", "operator.yaml", "README.md")
SCENARIOS = (
    ("demo-arid-ecology", "干旱区生态风险评估分析决策", "ecology"),
    ("demo-geology-reasoning", "地质逻辑推理", "geology"),
)
MINIMUM_BUDGETS = {"maxResources": 12, "maxIterations": 10, "maxOperatorSteps": 12}


def package(directory):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in PACKAGE_FILES:
            archive.writestr(name, (directory / name).read_bytes())
    return SimpleUploadedFile(directory.name + ".zip", buffer.getvalue())


def existing_demo_project(code: str, title: str, project_id=None):
    if project_id is not None:
        project = Project.objects.filter(pk=project_id, is_active=True).first()
        if project is None:
            raise CommandError("指定演示项目不存在或已停用")
        return project
    if title == "地质逻辑推理":
        matches = list(Project.objects.filter(name=title, is_active=True)[:2])
        if len(matches) > 1:
            raise CommandError("存在多个活动的地质逻辑推理项目，请先明确保留的项目")
        if matches:
            return matches[0]
    project = Project.objects.filter(code=code).first()
    if project is not None and not project.is_active:
        raise CommandError("已登记的演示项目已停用，请先核对项目状态")
    return project


def demo_project(user, code: str, title: str, *, project_id=None) -> Project:
    existing = existing_demo_project(code, title, project_id)
    if existing is not None:
        return existing
    project, _ = Project.objects.get_or_create(
        code=code,
        defaults={
            "name": title,
            "created_by": user,
            "description": "可重复演示项目，资料明确标注模拟；实际计算与结果保存。",
        },
    )
    if not project.is_active:
        raise CommandError("已登记的演示项目已停用，请先核对项目状态")
    return project


def version_source_matches(version: AlgorithmVersion, directory: Path) -> bool:
    path = app_path(version.package_path)
    try:
        if checksum(path) != version.checksum:
            raise CommandError("已登记算法包校验失败，请恢复原包或登记新版本")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            matches = all(
                names.count(name) == 1
                and archive.read(name) == (directory / name).read_bytes()
                for name in PACKAGE_FILES
            )
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise CommandError("已登记算法包无法核验，请恢复原包或登记新版本") from exc
    return matches


def verify_version_source(version: AlgorithmVersion, directory: Path) -> None:
    if not version_source_matches(version, directory):
        raise CommandError(
            f"算法 {version.algorithm.identifier} {version.version} 的源码已变化；"
            "请提高 operator.yaml 的版本号并登记新版本，原版本保持不变"
        )


def demo_policy_value(saved_value):
    value = {**default_policy(), **saved_value}
    for key, minimum in MINIMUM_BUDGETS.items():
        if not isinstance(value[key], int) or isinstance(value[key], bool):
            raise CommandError(f"现有策略 {key} 不是有效整数，请先核对策略")
        value[key] = max(value[key], minimum)
    return value


def preflight_algorithm_sources(program_root, projects):
    shared = []
    for name in ALGORITHMS:
        scenario = (
            "ecology"
            if name
            in {
                "raster-ndvi",
                "ndvi-change-candidates",
                "ecology-investigation-priority",
            }
            else "geology"
        )
        directory = program_root / "examples/compute" / name
        # Read all package members before any project, policy or resource writes.
        for filename in PACKAGE_FILES:
            (directory / filename).read_bytes()
        manifest = json.loads((directory / "operator.yaml").read_text(encoding="utf-8"))
        project = projects[scenario]
        if project is not None:
            version = AlgorithmVersion.objects.filter(
                algorithm__project_tag_id=project.id,
                algorithm__identifier=manifest["identifier"],
                version=manifest["version"],
            ).first()
            if version is not None:
                verify_version_source(version, directory)
        for version in AlgorithmVersion.objects.filter(
            algorithm__project_tag_id=1,
            algorithm__identifier=manifest["identifier"],
            version=manifest["version"],
        ):
            shared.append(
                {
                    "identifier": manifest["identifier"],
                    "version": version.version,
                    "versionId": version.id,
                    "sourceMatches": version_source_matches(version, directory),
                }
            )
    return shared


def import_table(user, path, code, name):
    existing = DataResource.objects.filter(code=code).first()
    if existing:
        return existing
    frame = pd.read_csv(path, keep_default_na=False)
    result = import_plain_table(
        df=frame,
        name=name,
        table_name=code.replace("-", "_"),
        metadata={},
        source_size_bytes=path.stat().st_size,
        user=user,
        access_group_ids=set(),
        domain_type="other",
        category=None,
    )
    resource = DataResource.objects.get(pk=result["resourceId"])
    resource.code, resource.source = code, "可复现模拟资料 双Demo"
    resource.description = (
        "模拟记录，字段、日期和对象匹配用于验证MH-workflow；不作为真实调查结论。"
    )
    resource.save()
    return resource


def import_vector(user, path, code, name, *, preserve_invalid=False):
    existing = DataResource.objects.filter(code=code).first()
    if existing:
        return existing
    if not preserve_invalid:
        result = commit_vector_import(
            SimpleUploadedFile(path.name, path.read_bytes()),
            {
                "name": name,
                "tableName": code.replace("-", "_"),
                "sourceLayerName": "data",
                "domainType": "other",
                "accessGroupIds": [],
            },
            user,
        )
        resource = DataResource.objects.get(pk=result["resourceId"])
    else:
        # Trusted synthetic fixture: retain the actual error for checking.
        # User uploads retain their existing validity gate.
        frame = gpd.read_file(path, layer="data")
        view = frame.to_crs(4326)
        target = vector_geopackage_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        layer_name = code.replace("-", "_")
        view.to_file(target, layer=layer_name, driver="GPKG", index=False)
        resource = upsert_vector_catalog_record(target, layer_name)
        summary = frame_summary(view)
        VectorDataset.objects.create(
            resource=resource,
            source_file_name=path.name,
            source_format="GPKG",
            source_layer_name="data",
            source_crs=str(frame.crs),
            source_epsg=frame.crs.to_epsg(),
            normalized_epsg=4326,
            geometry_type=summary["geometryType"],
            feature_count=len(view),
            vertex_count=summary["vertexCount"],
            field_count=len(summary["fields"]),
            valid_geometry_count=int(view.geometry.is_valid.sum()),
            invalid_geometry_count=int((~view.geometry.is_valid).sum()),
            bounds=summary["bounds"],
            import_summary={
                "synthetic": True,
                "preservedInvalidFixture": True,
                "stableFeatureIdField": "feature_id",
            },
        )
    resource.code, resource.name, resource.maintainer = code, name, user
    resource.source = "可复现模拟资料 双Demo"
    resource.description = (
        "模拟地图；研究输入角色已登记，独立参考图和设错清单未登记到平台。"
    )
    if preserve_invalid:
        resource.quality_note = (
            "模拟待检查初图：特意保留一处无效几何，供独立检查及人工审核候选。"
        )
    resource.save()
    for layer in resource.map_layers.all():
        layer.name = name
        layer.save(update_fields=["name"])
    return resource


def knowledge(user, key, domain, title, statement, conditions, sources):
    entry, created = KnowledgeEntry.objects.get_or_create(
        seed_key=key,
        defaults={
            "domain": domain,
            "title": title,
            "category": "双Demo依据",
            "subject": title[:120],
            "predicate": "适用条件",
            "object": "分析与调查动作",
            "statement": statement,
            "conditions": conditions,
            "sources": sources,
            "status": "published",
            "updated_by": user,
        },
    )
    if created:
        KnowledgeRevision.objects.create(
            entry=entry, revision=entry.revision, snapshot=serialize(entry)
        )
    return entry


class Command(BaseCommand):
    help = "准备双Demo本机项目、合成资料、必要知识及草稿算法；不自动发布"

    def add_arguments(self, parser):
        parser.add_argument("--geology-project-id", type=int)
        parser.add_argument("--user-id", type=int)

    def handle(self, **options):
        actors = get_user_model().objects.filter(is_active=True)
        if options.get("user_id") is not None:
            actors = actors.filter(pk=options["user_id"])
        user = next(
            (
                actor
                for actor in actors
                if actor.is_superuser or is_superadmin_user(actor)
            ),
            None,
        )
        if user is None:
            raise CommandError("先配置或指定有效超级管理员")
        base = settings.PROGRAM_ROOT / "examples/demos/dual-demo"
        projects = {
            scenario: existing_demo_project(
                code,
                title,
                options.get("geology_project_id") if scenario == "geology" else None,
            )
            for code, title, scenario in SCENARIOS
        }
        shared = preflight_algorithm_sources(settings.PROGRAM_ROOT, projects)
        for item in shared:
            if not item["sourceMatches"]:
                self.stderr.write(
                    f"公开算法 {item['identifier']} {item['version']} "
                    f"（版本 {item['versionId']}）源码与Demo不同；保留原版本和包，仅登记项目内副本。"
                )
        previous = AgentPolicy.objects.filter(pk=1).first()
        next_policy = demo_policy_value(
            previous.value if previous else {"operatorEnabled": True}
        )
        saved, _ = AgentPolicy.objects.get_or_create(
            pk=1, defaults={"value": next_policy}
        )
        if saved.value != next_policy:
            saved.value = next_policy
            saved.save(update_fields=["value", "updated_at"])
        spec = importlib.util.spec_from_file_location(
            "dual_samples", base / "generate_samples.py"
        )
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        sample_root = (
            settings.PROJECT_CONFIG.research_data_root
            / "demo-assets/dual-demo-20261010"
        )
        if not (sample_root / "manifest.json").exists():
            generator.generate(sample_root)
        record = {
            "sampleRoot": str(sample_root),
            "projects": {},
            "algorithmVersions": {},
            "sharedAlgorithmSources": shared,
        }
        for code, title, scenario in SCENARIOS:
            project = demo_project(
                user,
                code,
                title,
                project_id=projects[scenario].id if projects[scenario] else None,
            )
            ProjectMembership.objects.get_or_create(
                project=project, user=user, defaults={"assigned_by": user}
            )
            inputs = {}
            with project_scope(
                ProjectScope((project.id,), project.id, user.id, superadmin=True)
            ):
                folder = sample_root / scenario
                if scenario == "ecology":
                    for role, file, label, kind in [
                        (
                            "early_image",
                            "early.tif",
                            "前期影像 2025-09-15",
                            "imagery",
                        ),
                        ("late_image", "late.tif", "后期影像 2026-09-15", "imagery"),
                        ("valid_mask", "mask.tif", "两期共同有效掩膜", "categorical"),
                    ]:
                        marker = "demo-ecology-" + role.replace("_", "-")
                        resource = DataResource.objects.filter(source=marker).first()
                        if resource is None:
                            dataset = import_raster_file(
                                folder / file,
                                name="模拟 " + label,
                                raster_kind=kind,
                                uploader_id=user.id,
                            )
                            resource = dataset.data_resource
                            resource.source = marker
                            resource.description = "固定随机种子合成反射率；波段1红光、2近红外，比例1，30米，EPSG32645。"
                            resource.quality_note = (
                                "模拟质量掩膜用于流程验证，不是实际卫星云检测产品。"
                            )
                            resource.save()
                        inputs[role] = resource.id
                    inputs["zones"] = import_vector(
                        user,
                        folder / "zones.gpkg",
                        "demo-ecology-zones",
                        "模拟 四个调查分区",
                    ).id
                    inputs["context"] = import_table(
                        user,
                        folder / "context-initial.csv",
                        "demo-ecology-context-initial",
                        "模拟 初始生态背景与观测",
                    ).id
                    inputs["updated_context"] = import_table(
                        user,
                        folder / "context-updated.csv",
                        "demo-ecology-context-updated",
                        "模拟 补充收获记录后的观测",
                    ).id
                    official = "https://www.usgs.gov/landsat-missions/landsat-normalized-difference-vegetation-index"
                    knowledge(
                        user,
                        "demo-ndvi-scale",
                        "remote_sensing",
                        "NDVI公式与产品尺度",
                        "NDVI=(近红外−红光)/(近红外+红光)。官方Landsat指数整数产品需乘尺度因子；本演示使用Float反射率，输出[-1,1]指数。",
                        [
                            "按实际产品及波段核对定标",
                            "演示双波段排列不等同于任何完整传感器排列",
                        ],
                        [
                            {
                                "title": "USGS Landsat NDVI",
                                "url": official,
                                "locator": "公式与规格表",
                            }
                        ],
                    )
                    knowledge(
                        user,
                        "demo-valid-pixels",
                        "remote_sensing",
                        "有效像元与同季节植被比较",
                        "两期变化仅比较共同有效像元，云和阴影需由质量信息排除。匹配季节与网格，覆盖不足的区域先补资料。",
                        ["本演示同季节、同网格", "示范最低覆盖率0.65可配置"],
                        [
                            {
                                "title": "USGS Collection 2 QA",
                                "url": "https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands",
                                "locator": "QA_PIXEL Cloud/Cloud Shadow",
                            }
                        ],
                    )
                    knowledge(
                        user,
                        "demo-harvest-context",
                        "arid_ecology",
                        "植被下降线索与农田收获观测",
                        "两期NDVI下降只形成植被变化线索。匹配同分区、同期间且可信的农田收获记录时，可支持收获解释并调整调查优先级；独立缺水证据仍保留。",
                        ["模拟情景规则", "权重和可信度阈值为本次可配置演示参数"],
                        [
                            {
                                "title": "双Demo可复现样例说明",
                                "url": "",
                                "locator": "模拟调查规则与证据关联",
                            }
                        ],
                    )
                else:
                    inputs["initial_map"] = import_vector(
                        user,
                        folder / "initial.gpkg",
                        "demo-geology-initial",
                        "模拟 待检查初始填图",
                        preserve_invalid=True,
                    ).id
                    inputs["surveys"] = import_table(
                        user,
                        folder / "surveys.csv",
                        "demo-geology-surveys",
                        "模拟 地质调查记录",
                    ).id
                    inputs["rules"] = import_table(
                        user,
                        folder / "rules.csv",
                        "demo-geology-rules",
                        "模拟 允许属性修改规则",
                    ).id
                    knowledge(
                        user,
                        "demo-geology-evidence",
                        "geology",
                        "接触类型调查一致性检查",
                        "对象编号、工作投影位置、字段、允许值与可信度均匹配调查记录时，才能提出受约束属性纠正。低置信或矛盾记录保留待复核。几何修复另行检查并保留审核记录。",
                        ["小规则集模拟演示", "不以边界重合直接断言地质接触性质"],
                        [
                            {
                                "title": "双Demo可复现样例说明",
                                "url": "",
                                "locator": "结构化规则与受约束编辑",
                            }
                        ],
                    )
                record["projects"][scenario] = {
                    "id": project.id,
                    "name": project.name,
                    "inputs": inputs,
                }
        for name in ALGORITHMS:
            scenario = (
                "ecology"
                if name
                in {
                    "raster-ndvi",
                    "ndvi-change-candidates",
                    "ecology-investigation-priority",
                }
                else "geology"
            )
            pid = record["projects"][scenario]["id"]
            with project_scope(ProjectScope((pid,), pid, user.id, superadmin=True)):
                directory = settings.PROGRAM_ROOT / "examples/compute" / name
                manifest = json.loads(
                    (directory / "operator.yaml").read_text(encoding="utf-8")
                )
                algorithm, _ = AlgorithmResource.objects.get_or_create(
                    identifier=manifest["identifier"],
                    defaults={
                        "name": manifest["name"],
                        "description": manifest["description"],
                        "category": "双Demo",
                        "author": "STISP",
                        "created_by": user,
                    },
                )
                version = algorithm.versions.filter(version=manifest["version"]).first()
                if version is None:
                    version = store_version(algorithm, package(directory))
                else:
                    verify_version_source(version, directory)
                record["algorithmVersions"][algorithm.identifier] = version.id
        path = settings.PROGRAM_ROOT / ".runtime/dual-demo-20261010/objects.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.stdout.write(
            "两个Demo项目与输入已准备；复用已有算法状态，新登记版本需试运行通过后发布。对象清单已保存到私有运行目录。"
        )
