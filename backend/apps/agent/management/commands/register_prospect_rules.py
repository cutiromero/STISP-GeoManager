"""Register a separate v2 rule packet without changing frozen or original rules."""

import csv
from copy import deepcopy
import io
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.service import log_operation
from apps.catalog.models import DataResource
from apps.core.storage import table_data_path
from apps.knowledge.models import KnowledgeEntry, KnowledgeRevision
from apps.knowledge.prospect_rules import (
    CONDITION,
    METHOD,
    RESOURCE_CODE,
    VERSION,
    revised_rule,
)
from apps.knowledge.services import serialize
from apps.knowledge.trial_rules import SCENARIO, read_bound_rules
from apps.projects.context import ProjectScope, project_scope, is_superadmin
from apps.agent.tools import frame
from apps.agent.geology_multi import FIELDS


class Command(BaseCommand):
    help = "登记独立的修正后邻域组合规则包；保留旧知识、旧规则表及历史任务"

    def add_arguments(self, parser):
        parser.add_argument("--rules-resource", type=int, required=True)
        parser.add_argument("--actor", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        actor = get_user_model().objects.get(pk=options["actor"], is_active=True)
        if not is_superadmin(actor):
            raise CommandError("仅平台超级管理员可登记正式规则包")
        source = DataResource._base_manager.get(
            pk=options["rules_resource"], status="active"
        )
        if source.data_type != "table" or not source.code.startswith(
            "geology-multi-rules"
        ):
            raise CommandError("来源必须是已登记的地质规则包")
        with project_scope(
            ProjectScope((source.project_tag_id,), source.project_tag_id, actor.id)
        ):
            self.register(source, actor, options["apply"])

    def register(self, source, actor, apply):
        data, info = frame(source)
        if info.get("scope") == "prefix_sample" or not set(FIELDS) <= set(data.columns):
            raise CommandError("规则表不完整")
        rows = data.fillna("").to_dict(orient="records")
        bindings = [
            {
                "id": int(row["knowledge_id"]),
                "revision": int(row["knowledge_revision"]),
                "ruleId": row["rule_id"],
                "ruleVersion": row["rule_version"],
            }
            for row in rows
        ]
        entries = read_bound_rules(actor, source.project_tag_id, SCENARIO, bindings)
        selected = [row for row in rows if row["rule_id"] == "P-02"]
        if len(selected) != 1:
            raise CommandError("来源须且只能包含一条P-02")
        prior = next(
            entry for entry in entries if entry["trialBinding"]["ruleId"] == "P-02"
        )
        rule = revised_rule(prior["ruleConfig"]["rule"])
        config = deepcopy(prior["ruleConfig"])
        config.pop("formalRelease", None)
        config.update(
            parameters={**config["parameters"], "evidence_method": METHOD}, rule=rule
        )
        config["trialScope"]["ruleVersion"] = VERSION
        self.stdout.write(
            json.dumps(
                {
                    "source": source.id,
                    "project": source.project_tag_id,
                    "newRuleVersion": VERSION,
                    "code": RESOURCE_CODE,
                    "apply": apply,
                },
                ensure_ascii=False,
            )
        )
        if not apply:
            return
        with transaction.atomic():
            entry, created = KnowledgeEntry.objects.get_or_create(
                seed_key="geology-multi-P-02-prospect-v2",
                defaults={
                    "project_tag_id": source.project_tag_id,
                    "title": "P-02 构造与蚀变组合找矿目标",
                    "domain": "geology",
                    "category": "地质找矿规则",
                    "subject": prior["subject"],
                    "predicate": prior["predicate"],
                    "object": "修正后优先核查目标",
                    "statement": CONDITION,
                    "explanation": "大模型组织分析，算子测量并圈定少量有据目标；相对置信度为证据支持度。",
                    "conditions": [CONDITION],
                    "exceptions": [rule["basis"]["gap"]],
                    "aliases": ["P-02", "邻域矿物组合"],
                    "sources": [
                        {
                            "title": "五龙沟-海德乌拉地质找矿规则",
                            "url": "",
                            "locator": "P-02 " + VERSION,
                            "excerpt": CONDITION,
                        }
                    ]
                    + [
                        {
                            "title": reference["citation"][:300],
                            "url": "",
                            "locator": reference.get("verification", "区域适用待核查")[
                                :500
                            ],
                            "excerpt": "文献用于理解蚀变及构造背景；本项目邻域距离、组合方式及圈区参数需本区核查。",
                        }
                        for reference in rule.get("basis", {}).get("refs", [])
                    ],
                    "status": "published",
                    "rule_kind": "none",
                    "rule_config": config,
                    "updated_by": actor,
                },
            )
            if entry.rule_config != config or entry.status != "published":
                raise CommandError("已登记的2.0规则与候选内容不同，禁止覆盖")
            KnowledgeRevision.objects.get_or_create(
                entry=entry,
                revision=entry.revision,
                defaults={
                    "project_tag_id": source.project_tag_id,
                    "snapshot": serialize(entry),
                },
            )
            row = selected[0]
            row.update(
                knowledge_id=str(entry.id),
                knowledge_revision=str(entry.revision),
                rule_version=VERSION,
                rule_json=json.dumps(rule, ensure_ascii=False),
                params_json=json.dumps(config["parameters"], ensure_ascii=False),
            )
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            raw = stream.getvalue().encode("utf-8-sig")
            relative = "geology/prospect-v2/rules.csv"
            path = table_data_path(relative)
            existing = DataResource.objects.filter(code=RESOURCE_CODE).first()
            if existing:
                if (
                    existing.storage_path != "table/" + relative
                    or not path.is_file()
                    or path.read_bytes() != raw
                ):
                    raise CommandError("已登记的2.0规则包发生变化，禁止覆盖")
                resource = existing
            else:
                if path.exists():
                    raise CommandError("目标规则文件已存在且未登记，禁止覆盖")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                resource = DataResource.objects.create(
                    project_tag_id=source.project_tag_id,
                    name="五龙沟-海德乌拉_地质找矿规则",
                    code=RESOURCE_CODE,
                    data_type="table",
                    file_format="CSV",
                    storage_path="table/" + relative,
                    source="geology-multi-input:prospect-v2",
                    owner_only=source.owner_only,
                    maintainer=actor,
                    size_bytes=len(raw),
                    item_count=len(rows),
                    description="修正后构造与蚀变组合圈区；独立规则版本，原有知识与任务保留。",
                )
            log_operation(
                actor,
                "地质找矿",
                "登记修正后圈区规则",
                "success",
                resource.name,
                target_type="data_resource",
                target_id=resource.id,
            )
            self.stdout.write(
                json.dumps(
                    {
                        "resourceId": resource.id,
                        "knowledgeId": entry.id,
                        "knowledgeCreated": created,
                        "path": str(Path(path)),
                    },
                    ensure_ascii=False,
                )
            )
