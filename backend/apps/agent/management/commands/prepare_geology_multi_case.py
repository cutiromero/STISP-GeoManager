"""Idempotently register sanitized inputs and explicitly bound trial knowledge."""

import csv
import io
import json
from pathlib import Path
import zipfile

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.service import log_operation
from apps.catalog.importer import import_plain_table
from apps.catalog.models import DataResource
from apps.catalog.vector_importer import commit_vector_import
from apps.compute.models import AlgorithmCategory, AlgorithmResource
from apps.compute.project_tools import GEOLOGY_PROJECT_CODES
from apps.compute.views import store_version
from apps.core.storage import app_path
from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.services import serialize
from apps.projects.context import ProjectScope, is_superadmin, project_scope
from apps.projects.models import Project
from apps.raster.services.importer import import_raster_file

from .prepare_real_geology_case import checked_file, digest, import_artifact

SCENARIO = "geology_multi_element_reasoning"
PREFIX = "geology-multi-input:"
ROLES = {
    "lithology",
    "faults",
    "coverage",
    "hematite",
    "chlorite",
    "hydromica",
    "calcite",
    "dolomite",
}


def register_input(user, root, item, colors):
    path = checked_file(root, item)
    marker = PREFIX + item["sha256"]
    existing = DataResource.objects.filter(code=item["code"]).first()
    if existing:
        if existing.source != marker or existing.status != "active":
            raise CommandError(
                "同编码资料已变化，请保存新版本并重新登记：" + item["code"]
            )
        return existing
    if item["kind"] == "vector":
        value = commit_vector_import(
            SimpleUploadedFile(path.name, path.read_bytes()),
            {
                "name": item["name"],
                "tableName": item["code"].replace("-", "_"),
                "sourceLayerName": "data",
                "domainType": "other",
                "categoryCode": "spatial",
                "accessGroupIds": [],
            },
            user,
        )
        resource = DataResource.objects.get(pk=value["resourceId"])
    elif item["kind"] == "table":
        value = import_plain_table(
            df=pd.read_csv(path, dtype=str, keep_default_na=False),
            name=item["name"],
            table_name=item["code"].replace("-", "_"),
            metadata={},
            source_size_bytes=path.stat().st_size,
            user=user,
            access_group_ids=set(),
            domain_type="other",
            category=None,
        )
        resource = DataResource.objects.get(pk=value["resourceId"])
    elif item["kind"] == "raster":
        resource = import_raster_file(
            path, name=item["name"], raster_kind="categorical", uploader_id=user.id
        ).data_resource
    else:
        raise CommandError("只支持已核对的矢量、表格与栅格")
    resource.code, resource.source = item["code"], marker
    resource.description, resource.provider = item["description"], "海德乌拉演示案例"
    if item.get("role") == "lithology":
        visualization = dict(resource.default_visualization)
        visualization["symbolization"] = {
            "opacity": 90,
            "renderer": {
                "type": "uniqueValue",
                "field": "name",
                "classes": [
                    {
                        "id": f"legend-{index}",
                        "value": name,
                        "label": name,
                        "color": color,
                    }
                    for index, (name, color) in enumerate(colors.items())
                ],
                "defaultClass": {"color": "#cbd5e1", "label": "其他"},
            },
            "line": {"lineColor": "#64748b", "lineWidth": 0.5},
        }
        resource.default_visualization = visualization
    resource.save()
    log_operation(
        user,
        "海德乌拉综合推理",
        "导入运行资料",
        "success",
        resource.name,
        target_type="data_resource",
        target_id=resource.id,
    )
    return resource


def register_knowledge(user, project, bundle):
    entries = []
    for rule in bundle["rules"]:
        basis = rule.get("basis", {})
        sources = [
            {
                "title": "海德乌拉演示规则集",
                "url": "",
                "locator": f"knowledge/rules.yaml {rule['id']} {bundle['version']}",
                "excerpt": basis.get("statement", "")[:1200],
            }
        ]
        sources.extend(
            {
                "title": item["citation"][:300],
                "url": "",
                "locator": item.get("verification", "交付材料引用，待核实")[:500],
                "excerpt": basis.get("statement", "")[:1200],
            }
            for item in basis.get("refs", [])
        )
        exceptions = [basis["gap"]] if basis.get("gap") else []
        if rule["id"].startswith("L-") and rule["id"] != "L-03":
            exceptions.append(
                "残留体、构造窗、捕虏体等地质例外需进一步证据；面积和时代排序只构成疑点。"
            )
        values = {
            "domain": "geology",
            "title": f"{rule['id']} {rule['name']}（本案例试用）",
            "category": "海德乌拉" + rule["element"] + "试用规则",
            "subject": rule.get("applies_to", rule["element"]),
            "predicate": rule.get("relation", "检查依据"),
            "object": rule["name"],
            "statement": rule["condition"],
            "explanation": f"依据类型：{basis.get('type', '经验假设')}。{basis.get('statement', '')}\n原草案处理建议：{rule.get('action', '参与综合条件判断')}。本场景所有实际修改须经用户批准；模拟置信度仅供演示，A/B为证据组合等级。",
            "conditions": [
                "仅适用于青海东昆仑海德乌拉演示案例",
                "本案例试用，参数与区域适用性待专家核对",
                rule["condition"],
            ],
            "exceptions": exceptions,
            "aliases": [rule["id"], rule["name"]],
            "sources": sources,
            "status": "draft",
            "rule_kind": "none",
            "rule_config": {
                "trialScope": {
                    "scenario": SCENARIO,
                    "projectId": project.id,
                    "ruleId": rule["id"],
                    "ruleVersion": bundle["version"],
                },
                "parameters": {
                    **rule.get("params", {}),
                    **rule.get("action_params", {}),
                },
                "rule": rule,
            },
        }
        with transaction.atomic():
            entry, created = KnowledgeEntry.objects.get_or_create(
                seed_key="geology-multi-" + rule["id"],
                defaults={**values, "updated_by": user},
            )
            if not created:
                if entry.status != "draft":
                    raise CommandError("试用规则状态已变化，请人工审查后登记新版本")
                if any(getattr(entry, key) != value for key, value in values.items()):
                    KnowledgeRevision.objects.get_or_create(
                        entry=entry,
                        revision=entry.revision,
                        defaults={"snapshot": serialize(entry)},
                    )
                    for key, value in values.items():
                        setattr(entry, key, value)
                    entry.revision += 1
                    entry.updated_by = user
                    entry.save()
            KnowledgeRevision.objects.get_or_create(
                entry=entry,
                revision=entry.revision,
                defaults={"snapshot": serialize(entry)},
            )
        entries.append(entry)
    return entries


def register_packages(user, directory):
    output = {}
    for suffix in ("check", "apply", "relations", "prospect"):
        identifier = "geology-multi-" + suffix
        path = directory / (identifier + ".zip")
        data = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            spec = json.loads(archive.read("operator.yaml"))
        if spec["identifier"] != identifier:
            raise CommandError("包标识不一致")
        algorithm, _ = AlgorithmResource.objects.get_or_create(
            identifier=identifier,
            defaults={
                "name": spec["name"],
                "description": spec["description"],
                "category": "地质综合推理",
                "author": spec["author"],
                "created_by": user,
            },
        )
        version = algorithm.versions.filter(version=spec["version"]).first()
        if version is None:
            version = store_version(algorithm, SimpleUploadedFile(path.name, data))
        elif (
            version.checksum != digest(path)
            or digest(app_path(version.package_path)) != version.checksum
        ):
            raise CommandError("已登记版本源码变化，请登记新版本并保留旧版本")
        output[identifier] = version.id
    AlgorithmCategory.objects.get_or_create(
        name="地质综合推理", defaults={"sort_order": 30}
    )
    return output


class Command(BaseCommand):
    help = "导入海德乌拉去标签资料与受限试用知识；只登记算法草稿，不自动发布"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--record", type=Path, required=True)
        parser.add_argument("--packages", type=Path)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, **options):
        user = (
            get_user_model()
            .objects.filter(pk=options["user_id"], is_active=True)
            .first()
        )
        project = Project.objects.filter(
            pk=options["project_id"], is_active=True, code__in=GEOLOGY_PROJECT_CODES
        ).first()
        if user is None or not is_superadmin(user) or project is None:
            raise CommandError("请选择现有逻辑推理项目与有效超级管理员")
        root = options["manifest"].resolve().parent
        manifest = json.loads(options["manifest"].read_text(encoding="utf-8"))
        bundle = json.loads((root / "trial_knowledge.json").read_text(encoding="utf-8"))
        if (
            manifest.get("scenario") != SCENARIO
            or {item["role"] for item in manifest["resources"]} != ROLES
            or len(manifest["resources"]) != 8
            or len(bundle["rules"]) != 17
            or bundle.get("scenario") != SCENARIO
        ):
            raise CommandError("运行资料或试用知识清单不完整")
        for item in [*manifest["resources"], *manifest["artifacts"]]:
            checked_file(root, item)
        if options["dry_run"]:
            self.stdout.write("8项输入、17条试用规则与2项参考成果预检通过；无业务写入")
            return
        record = {
            "projectId": project.id,
            "resources": {},
            "knowledge": {},
            "algorithms": {},
            "artifacts": {},
        }
        with project_scope(ProjectScope((project.id,), project.id, user.id, True)):
            entries = register_knowledge(user, project, bundle)
            fields = [
                "rule_id",
                "rule_version",
                "knowledge_id",
                "knowledge_revision",
                "params_json",
                "rule_json",
                "units_json",
                "aliases_json",
            ]
            rule_path = root / "inputs/rules.csv"
            with rule_path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for index, entry in enumerate(entries):
                    config = entry.rule_config
                    writer.writerow(
                        {
                            "rule_id": config["trialScope"]["ruleId"],
                            "rule_version": bundle["version"],
                            "knowledge_id": entry.id,
                            "knowledge_revision": entry.revision,
                            "params_json": json.dumps(
                                config["parameters"], ensure_ascii=False
                            ),
                            "rule_json": json.dumps(config["rule"], ensure_ascii=False),
                            "units_json": json.dumps(
                                bundle["units"], ensure_ascii=False
                            )
                            if index == 0
                            else "",
                            "aliases_json": json.dumps(
                                bundle["aliases"], ensure_ascii=False
                            )
                            if index == 0
                            else "",
                        }
                    )
                    record["knowledge"][config["trialScope"]["ruleId"]] = {
                        "id": entry.id,
                        "revision": entry.revision,
                    }
            rule_item = {
                "file": "inputs/rules.csv",
                "sha256": digest(rule_path),
                "code": "geology-multi-rules",
                "kind": "table",
                "name": "海德乌拉本案例试用规则",
                "description": "17条草拟规则及34个归一化代号、38种名称映射；仅本项目本场景显式绑定后读取。",
            }
            resources = {}
            colors = json.loads(
                (root / "legend_colors.json").read_text(encoding="utf-8")
            )
            for item in [*manifest["resources"], rule_item]:
                value = register_input(user, root, item, colors)
                resources[item["code"]] = value
                record["resources"][item["code"]] = value.id
            for item in manifest["artifacts"]:
                record["artifacts"][item["name"]] = import_artifact(
                    user, project, root, item, resources
                ).id
            if options["packages"]:
                record["algorithms"] = register_packages(user, options["packages"])
        options["record"].parent.mkdir(parents=True, exist_ok=True)
        options["record"].write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.stdout.write(
            f"已登记{len(record['resources'])}项输入、17条试用知识及2项参考成果；原包与独立评价资料未登记为运行输入"
        )
