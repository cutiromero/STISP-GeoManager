"""Plan input conversions from published capabilities, independently of a domain."""

import re

from django.core.exceptions import ValidationError

from apps.compute.models import AlgorithmVersion
from apps.compute.services import agent_algorithm_allowed, allowed_algorithms

KINDS = {"vector", "raster", "table", "image", "document", "gene"}
MAX_ADAPTERS = 60
MAX_INPUTS = 30


def capabilities(user, *, pinned=()):
    rows = (
        AlgorithmVersion.objects.select_related("algorithm")
        .filter(
            algorithm__in=allowed_algorithms(),
            algorithm__enabled=True,
            status="published",
            manifest__inputAdapter__isnull=False,
        )
        .order_by("algorithm_id", "-created_at", "-id")
    )
    found = {}
    selected = []
    for version in rows:
        if (
            version.algorithm_id not in found or version.pk in pinned
        ) and agent_algorithm_allowed(version):
            found[version.algorithm_id] = version
            selected.append(version)
            if len(found) > MAX_ADAPTERS:
                raise ValidationError("当前可用适配能力过多，请按项目整理已发布算子")
    return selected


def logical_role(key, requirements):
    if key in requirements:
        return key
    match = re.fullmatch(r"([a-z][a-z0-9_-]{1,63}):([1-9][0-9]{0,15})", key)
    if (
        match
        and match[1] in requirements
        and requirements[match[1]].get("multiple", False)
    ):
        return match[1]
    raise ValidationError("输入角色未在业务流中声明：" + str(key))


def _parameters(version, metadata, selected):
    specs = {item["key"]: item for item in version.manifest["parameters"]}
    if not isinstance(selected, dict) or set(selected) - set(specs):
        raise ValidationError("输入适配包含未声明的算子参数")
    result, missing = {}, []
    fields = metadata.get("fields", [])
    fields = [item["name"] if isinstance(item, dict) else item for item in fields]
    hints = version.manifest["inputAdapter"].get("fieldHints", {})
    metadata_parameters = version.manifest["inputAdapter"].get("metadataParameters", {})
    for key, spec in specs.items():
        condition = spec.get("when")
        if condition and result.get(condition["key"]) != condition["equals"]:
            continue
        if key in selected:
            value = selected[key]
            if spec["type"] == "field" and value not in fields:
                raise ValidationError("适配字段不属于实际来源：" + key)
            result[key] = value
        elif key in metadata_parameters and metadata.get(metadata_parameters[key]):
            result[key] = metadata[metadata_parameters[key]]
        elif "default" in spec:
            result[key] = spec["default"]
        elif spec["type"] == "field":
            ranked = [
                (
                    max(
                        (
                            len(hint)
                            for hint in hints.get(key, [])
                            if hint.casefold() in field.casefold()
                        ),
                        default=0,
                    ),
                    field,
                )
                for field in fields
            ]
            best = max((score for score, _ in ranked), default=0)
            candidates = [
                field for score, field in ranked if score == best and score > 0
            ]
            if len(candidates) == 1:
                result[key] = candidates[0]
            elif spec.get("required", True):
                missing.append(key)
        elif spec.get("required", True):
            missing.append(key)
    if not missing:
        from apps.compute.services import parameter_values

        result = parameter_values(
            version.manifest,
            {
                version.manifest["inputAdapter"]["inputKey"]: {
                    **metadata,
                    "fields": fields,
                }
            },
            result,
        )
    return result, missing


def plan_inputs(user, requirements, sources, choices=None, *, available=None):
    """Return explainable direct/convert/configuration plans; never run a task."""
    if len(sources) > MAX_INPUTS:
        raise ValidationError("本次输入资料超过业务流上限")
    choices = {} if choices is None else choices
    if not isinstance(choices, dict) or set(choices) - set(sources):
        raise ValidationError("适配选择包含未知的输入角色")
    versions = available
    specs = {item["key"]: item for item in requirements}
    plans = []
    for key, source in sources.items():
        spec = specs[logical_role(key, specs)]
        resource, metadata = source
        semantics = spec.get("semanticType", "")
        direct = (
            resource.data_type in spec["dataTypes"]
            and (not semantics or metadata.get("semanticType") == semantics)
            and set(spec.get("requiredFields", []))
            <= {
                field["name"] if isinstance(field, dict) else field
                for field in metadata.get("fields", [])
            }
        )
        item = {
            "role": key,
            "sourceId": resource.pk,
            "sourceName": resource.name,
            "sourceType": resource.data_type,
            "sourceRevision": resource.updated_at.isoformat(),
            "sourceBands": metadata.get("bands", metadata.get("bandCount", 0)) or 0,
            "targetTypes": spec["dataTypes"],
            "targetSemantics": semantics,
            "status": "direct" if direct else "unavailable",
            "fields": [
                field["name"] if isinstance(field, dict) else field
                for field in metadata.get("fields", [])
            ],
            "candidates": [],
        }
        choice = choices.get(key, {})
        if not isinstance(choice, dict) or set(choice) - {"versionId", "parameters"}:
            raise ValidationError("输入适配选择格式无效")
        if "versionId" in choice and (
            type(choice["versionId"]) is not int or choice["versionId"] < 1
        ):
            raise ValidationError("适配版本编号须为正整数")
        if direct and not choice:
            plans.append(item)
            continue
        if versions is None:
            versions = capabilities(
                user,
                pinned=[
                    choice.get("versionId")
                    for choice in choices.values()
                    if isinstance(choice, dict)
                ],
            )
        matching_by_algorithm = {}
        for version in versions:
            cap = version.manifest["inputAdapter"]
            if (
                cap["sourceKind"] == resource.data_type
                and cap["targetKind"] in spec["dataTypes"]
                and (not semantics or cap.get("targetSemantics") == semantics)
                and set(spec.get("requiredFields", []))
                <= set(cap.get("outputFields", []))
            ):
                algorithm_id = version.algorithm_id
                if (
                    algorithm_id not in matching_by_algorithm
                    or version.pk == choice.get("versionId")
                ):
                    matching_by_algorithm[algorithm_id] = version
        matching = list(matching_by_algorithm.values())
        item["candidates"] = [
            {
                "versionId": version.pk,
                "name": version.algorithm.name,
                "description": version.manifest["inputAdapter"].get("description", ""),
                "parameters": version.manifest["parameters"],
                "targetType": version.manifest["inputAdapter"]["targetKind"],
            }
            for version in matching
        ]
        selected = (
            next(
                (
                    version
                    for version in matching
                    if version.pk == choice.get("versionId")
                ),
                None,
            )
            if choice.get("versionId")
            else matching[0]
            if len(matching) == 1 and bool(semantics)
            else None
        )
        if choice.get("versionId") and selected is None:
            raise ValidationError("所选适配算子未发布、无权调用或不满足输入规范")
        if selected:
            parameters, missing = _parameters(
                selected,
                {
                    **metadata,
                    "sourceName": resource.name,
                    "sourceType": resource.data_type,
                },
                choice.get("parameters", {}),
            )
            cap = selected.manifest["inputAdapter"]
            item.update(
                status="needs_parameters" if missing else "convert",
                versionId=selected.pk,
                checksum=selected.checksum,
                inputKey=cap["inputKey"],
                outputKey=cap["outputKey"],
                targetType=cap["targetKind"],
                parameters=parameters,
                missingParameters=missing,
                fieldTargets=cap.get("fieldTargets", {}),
            )
        elif matching:
            item["status"] = "needs_choice"
        plans.append(item)
    return {
        "ready": all(item["status"] in {"direct", "convert"} for item in plans),
        "items": plans,
    }
