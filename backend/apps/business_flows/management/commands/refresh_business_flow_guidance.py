"""Apply the official research guidance to the current published definitions."""

from copy import deepcopy
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import F

from apps.projects.context import ProjectScope, is_superadmin, project_scope

from ...builtins import builtin_flows
from ...catalog import publish_version, require_author, validate_bindings
from ...definitions import normalize_definition
from ...models import BusinessFlowDefinition
from ... import monitoring_presets


class Command(BaseCommand):
    help = (
        "更新官方流程的科研目的、节点判断指导和知识问题，保留当前执行合同。默认预览。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *, user_id, apply, **options):
        user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
        if not user or not is_superadmin(user):
            raise CommandError("请选择有效的超级管理员账号")
        builtins = {row["code"]: row["definition"] for row in builtin_flows()}
        flows = (
            BusinessFlowDefinition._base_manager.filter(
                code__in=set(builtins) | set(monitoring_presets.PRESETS),
                is_active=True,
                project_tag__is_active=True,
                current_version__status="published",
            )
            .select_related("current_version")
            .order_by("pk")
        )
        results = []
        with transaction.atomic():
            if apply and connection.vendor == "sqlite":
                BusinessFlowDefinition._base_manager.filter(
                    pk__in=flows.values("pk")
                ).update(updated_at=F("updated_at"))
            for flow in flows:
                version = flow.current_version
                old = version.definition
                template = builtins.get(flow.code)
                if template is None:
                    algorithm = next(
                        (
                            row.get("algorithmVersionId")
                            for row in old["nodes"]
                            if row["id"] == "interpret"
                        ),
                        None,
                    )
                    if algorithm is None:
                        raise CommandError(f"流程 {flow.pk} 缺少当前监测算子版本")
                    template = monitoring_presets.definition(flow.code, algorithm)
                guidance = {node["id"]: node for node in template["nodes"]}
                if template["adapter"] != old["adapter"] or set(guidance) != {
                    node["id"] for node in old["nodes"]
                }:
                    raise CommandError(
                        f"流程 {flow.pk} 的节点结构已变更，请单独核对科研说明"
                    )
                updated = deepcopy(old)
                updated["skill"] = deepcopy(template["skill"])
                for node in updated["nodes"]:
                    source = guidance[node["id"]]
                    for field in ("description", "instruction"):
                        node[field] = source[field]
                    if node.get("contract") and source.get("contract"):
                        node["contract"]["goal"] = source["contract"]["goal"]
                spec = normalize_definition(updated, authored=True)
                changed = spec != old
                with project_scope(
                    ProjectScope((flow.project_tag_id,), flow.project_tag_id, user.pk)
                ):
                    require_author(user, flow)
                    validate_bindings(spec, flow.project_tag_id)
                    if changed and apply:
                        _, current = publish_version(
                            user,
                            flow,
                            spec,
                            expected=flow.updated_at.isoformat(),
                            authored=True,
                        )
                    else:
                        current = version
                results.append(
                    {
                        "id": flow.pk,
                        "projectId": flow.project_tag_id,
                        "code": flow.code,
                        "previousVersion": version.version,
                        "currentVersion": current.version,
                        "changed": changed,
                        "knowledgeQuestions": len(
                            spec["skill"].get("knowledgeQuestions", [])
                        ),
                    }
                )
        self.stdout.write(
            json.dumps({"applied": apply, "items": results}, ensure_ascii=False)
        )
