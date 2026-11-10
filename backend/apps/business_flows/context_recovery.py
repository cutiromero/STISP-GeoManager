"""上下文等待复用节点决定通道，但绝不写科研人工批准。"""

from django.core.exceptions import ValidationError

from apps.compute.packages import ComputeError


def retry_node(workflow, item, value):
    recovery = item["contextRecovery"]
    skipped = value.get("skipEvidenceIds", [])
    scope = value.get("contextScope", {})
    if (
        not isinstance(skipped, list)
        or any(not isinstance(identity, str) for identity in skipped)
        or len(skipped) != len(set(skipped))
    ):
        raise ValidationError("跳过证据必须是无重复编号数组")
    allowed = {row["id"] for row in recovery.get("evidence", []) if not row["required"]}
    if set(skipped) - allowed:
        raise ComputeError("不能跳过必需、直接依赖或未提供的证据", 409)
    previously_skipped = set(item.get("contextOptions", {}).get("skipEvidenceIds", []))
    remaining = {row["id"] for row in recovery.get("evidence", [])} - previously_skipped
    if skipped and not remaining - set(skipped):
        raise ComputeError("不能跳过全部证据；请保留至少一项实际资料或停止任务", 409)
    if not isinstance(scope, dict) or set(scope) - {"maxItems", "maxTextCharacters"}:
        raise ValidationError("上下文范围无效")
    for key, lower, upper in (("maxItems", 1, 10), ("maxTextCharacters", 80, 1000)):
        if key in scope and (
            type(scope[key]) is not int or not lower <= scope[key] <= upper
        ):
            raise ValidationError("上下文范围必须在允许的收紧区间内")
    options = item.setdefault("contextOptions", {})
    options["skipEvidenceIds"] = list(
        dict.fromkeys([*options.get("skipEvidenceIds", []), *skipped])
    )
    options["contextScope"] = {
        **options.get("contextScope", {}),
        **{
            key: min(value, options.get("contextScope", {}).get(key, value))
            for key, value in scope.items()
        },
    }
    options["scope"] = value.get("feedback", "").strip()
    if skipped or scope or options["scope"]:
        item.pop("reviewContextBudget", None)
        item.pop("reviewRepacks", None)
    if recovery.get("preparationRole") and (skipped or scope or options["scope"]):
        preparation = next(
            row
            for row in workflow.plan.get("inputAdaptations", [])
            if row["role"] == recovery["preparationRole"]
        )
        if preparation.pop("contextDraft", None):
            preparation["scriptAttempt"] -= 1
        item.pop("executionContextId", None)
    if not recovery.get("preparationRole") and (skipped or scope or options["scope"]):
        if not item.get("computeTaskId"):
            item["executor"] = {"status": "pending"}
            item["reviewer"] = {"status": "pending"}
            item["outputs"] = {}
            item.pop("executionContextId", None)
    item["status"] = "executing" if item["attempt"] else "pending"
    item.pop("contextRecovery")
