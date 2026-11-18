"""Publish new versions from the exact operators already validated for each project."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import F

from apps.business_flows.catalog import publish_version, validate_bindings
from apps.business_flows.definitions import normalize_definition
from apps.business_flows.monitoring_presets import GOALS, PRESETS, definition
from apps.business_flows.models import BusinessFlowDefinition
from apps.compute.models import AlgorithmVersion
from apps.projects.context import ProjectScope, is_superadmin, project_scope


class Command(BaseCommand):
    help = "核对或发布已有遥感监测流程的新版主Agent定义，不改旧版本、不触发计算。"

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *, actor, apply, **kwargs):
        user = get_user_model().objects.filter(username=actor, is_active=True).first()
        if user is None or not is_superadmin(user):
            raise CommandError("请指定有效的超级管理员账号")
        with transaction.atomic():
            if apply and connection.vendor == "sqlite":
                BusinessFlowDefinition._base_manager.filter(
                    code__in=PRESETS,
                    is_active=True,
                    project_tag__is_active=True,
                ).update(updated_at=F("updated_at"))
            for flow in (
                BusinessFlowDefinition._base_manager.filter(
                    code__in=PRESETS,
                    is_active=True,
                    project_tag__is_active=True,
                )
                .select_related("current_version")
                .order_by("pk")
            ):
                current = flow.current_version
                if current is None or current.status != "published":
                    raise CommandError(f"流程 {flow.pk} 没有可核对的已发布版本")
                operator = next(
                    (
                        row
                        for row in current.definition["nodes"]
                        if row["id"] == "interpret"
                    ),
                    {},
                )
                ident = operator.get("algorithmVersionId")
                if not AlgorithmVersion.objects.filter(
                    pk=ident,
                    status="published",
                    algorithm__identifier=PRESETS[flow.code][1],
                ).exists():
                    raise CommandError(f"流程 {flow.pk} 未绑定预期的已发布算子")
                with project_scope(
                    ProjectScope((flow.project_tag_id,), flow.project_tag_id, user.pk)
                ):
                    spec = normalize_definition(definition(flow.code, ident))
                    validate_bindings(spec, flow.project_tag_id)
                    if current.definition == spec:
                        self.stdout.write(
                            f"{flow.pk} {flow.code} v{current.version} 已是相同主Agent定义"
                        )
                        continue
                    version = None
                    if apply:
                        _, version = publish_version(
                            user,
                            flow,
                            spec,
                            expected=flow.updated_at.isoformat(),
                            metadata={"description": GOALS[flow.code]},
                        )
                    self.stdout.write(
                        f"{flow.pk} {flow.code} 算子={ident} "
                        + (
                            f"已发布 v{version.version}"
                            if version
                            else f"准备从 v{current.version} 发布新版本"
                        )
                    )
