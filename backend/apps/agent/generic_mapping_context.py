"""Bound rule hints for displayed profile samples, with live authorization."""

from copy import deepcopy

from django.core.exceptions import PermissionDenied, ValidationError

from apps.compute.packages import ComputeError
from apps.knowledge.trial_rules import digest

from . import geology_multi

# Configuration: these are the existing upload profile's sampling limits.
MAX_SAMPLES = 8
MAX_SAMPLE_CHARACTERS = 80
PROFILE_ROW_LIMIT = 1000
PLAN_KEYS = (
    "uploadInputs",
    "uploadBatchId",
    "rulesResourceId",
    "knowledgeSelection",
    "unitOverrides",
    "phase",
    "effectiveInputs",
    "preparedInputProfiles",
)


class MappingRuleContextError(ValidationError):
    """Invalid bound rules must stop mapping instead of triggering name fallback."""


def _state(workflow):
    return digest(
        {
            "plan": {key: workflow.plan.get(key) for key in PLAN_KEYS},
            "workflowType": workflow.workflow_type,
            "goal": workflow.goal,
            "resourceIds": workflow.resource_ids,
        }
    )


def shown_samples(field):
    return [
        str(value)[:MAX_SAMPLE_CHARACTERS]
        for value in field.get("samples", [])[:MAX_SAMPLES]
    ]


def _sample_matches(field, units, aliases):
    samples = shown_samples(field)
    untruncated = [value for value in samples if len(value) < MAX_SAMPLE_CHARACTERS]
    return {
        "sampleCount": len(samples),
        "aliasExactSampleCount": sum(value in aliases for value in samples),
        "unitCodeExactSampleCount": sum(value in units for value in samples),
        "possiblyTruncatedSampleCount": len(samples) - len(untruncated),
        "untruncatedAliasMatchCount": sum(value in aliases for value in untruncated),
        "untruncatedUnitCodeMatchCount": sum(value in units for value in untruncated),
    }


class MappingRuleContext:
    def __init__(self, workflow, roles):
        self._state = _state(workflow)
        self._roles = deepcopy(roles)
        self._uploads = None
        self._rules = None
        self.payload = None

    def authorize(self, workflow, user, policy):
        """Called only inside ModelStreamGuard, including the initial rule read."""
        from .logic_configuration import snapshot
        from .models import WorkflowUpload
        from .workflow_resources import (
            resolve_upload_resource,
            resolve_workflow_resource,
        )

        if _state(workflow) != self._state:
            raise PermissionDenied("字段判断的资料、规则或知识设置已变化，请重新核对")
        uploads = {}
        for role, identity in workflow.plan.get("uploadInputs", {}).items():
            resource = resolve_upload_resource(
                user,
                policy,
                identity,
                workflow.plan["uploadBatchId"],
                workflow=workflow,
            )
            upload = WorkflowUpload.objects.select_related("resource").get(
                owner=user,
                project_tag_id=workflow.project_tag_id,
                workflow=workflow,
                resource_id=identity,
                batch_id=workflow.plan["uploadBatchId"],
            )
            upload.resource = resource
            uploads[role] = {
                "snapshot": snapshot(upload),
                "source": upload.source,
                "id": str(upload.pk),
            }
            for item in self._roles:
                if item["role"] != role:
                    continue
                effective = workflow.plan.get("effectiveInputs", {}).get(role, identity)
                expected = upload.profile
                if effective != identity:
                    prepared = resolve_workflow_resource(
                        user, policy, effective, workflow
                    )
                    key = str(effective) + ":" + prepared.updated_at.isoformat()
                    expected = workflow.plan.get("preparedInputProfiles", {}).get(key)
                    uploads[role]["prepared"] = {
                        "resourceId": prepared.pk,
                        "revision": prepared.updated_at.isoformat(),
                    }
                if (
                    item["resourceId"] != effective
                    or expected is None
                    or item["_profile"] != expected
                ):
                    raise PermissionDenied("字段判断的资料样本已变化，请重新核对")
        if self._uploads is not None and uploads != self._uploads:
            raise PermissionDenied("字段判断的资料版本已变化，请重新核对")
        self._uploads = uploads

        identity = workflow.plan.get("rulesResourceId")
        if identity is None:
            return
        if workflow.plan.get("knowledgeSelection", {}).get("mode") == "none":
            raise PermissionDenied(
                "字段判断需要读取本任务绑定的地质规则，请启用知识依据"
            )
        try:
            resource, entries, units, aliases = geology_multi.read_rules(
                user, policy, identity, workflow=workflow
            )
            # read_rules validates ACL and bindings. Freeze all consumed table
            # cells too, including params/rule cells superseded by bound knowledge.
            data, info = geology_multi.frame(resource)
            if info.get("scope") == "prefix_sample" or not 1 <= len(data) <= 40:
                raise ComputeError("字段判断的绑定规则表必须完整且不超过40条")
            rows = data.loc[:, list(geology_multi.FIELDS)].fillna("").astype(str)
            current = digest(
                [
                    resource.updated_at.isoformat(),
                    entries,
                    units,
                    aliases,
                    rows.to_dict("records"),
                ]
            )
            units, aliases = geology_multi.effective_units(workflow, units, aliases)
        except (
            ComputeError,
            ValidationError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            raise MappingRuleContextError(
                "字段判断绑定的规则内容无效或不可读取，请修复后重试"
            ) from exc
        if self._rules is not None and current != self._rules:
            raise PermissionDenied("字段判断的规则内容或知识绑定已变化，请重新核对")
        self._rules = current
        if self.payload is None:
            override = workflow.plan.get("unitOverrides") or {}
            units_status = (
                "confirmed_override"
                if override.get("units") or override.get("aliases")
                else "pending_confirmation"
                if "units" in workflow.plan.get("uploadInputs", {})
                else "not_uploaded"
            )
            self.payload = {
                "summary": {
                    "scope": "displayed_profile_samples",
                    "profileRowLimit": PROFILE_ROW_LIMIT,
                    "maxSamplesPerField": MAX_SAMPLES,
                    "maxSampleCharacters": MAX_SAMPLE_CHARACTERS,
                    "userUnitsStatus": units_status,
                    "limitation": (
                        "统计仅比较profile已显示样本与任务绑定词表的精确相等；"
                        "每字段最多8个展示样本，计数不是行数，来自前1000行，"
                        "distinctCount也只覆盖此前缀，每值最多80字符。"
                        "长度达到80字符可能已截断，此时展示值命中不证明完整原值命中；"
                        "未命中不能推断没有适用规则，统计不代表全表覆盖率。"
                        "用户units表在字段确认后可覆盖默认词表；已确认覆盖按同名或同代号优先。"
                        "这些提示只辅助模型判断，字段对应仍需用户确认。"
                    ),
                },
                "fields": {
                    item["role"]: {
                        field["name"]: _sample_matches(field, units, aliases)
                        for field in item["_profile"].get("fields", [])
                    }
                    for item in self._roles
                },
            }
