"""Shared scenario protocol, current-data validation and frozen trial-rule inputs."""

from __future__ import annotations

import csv
import io
import json
import math

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.catalog.models import DataResource
from apps.compute.access import require_actor
from apps.compute.data import candidate
from apps.compute.packages import ComputeError, checksum
from apps.core.storage import table_data_path
from apps.knowledge.services import search_entries
from apps.knowledge.trial_rules import SCENARIO, digest, read_bound_rules
from .tools import frame, resolve_resource

ROLES = {
    "lithology": "vector",
    "faults": "vector",
    "coverage": "vector",
    "rules": "table",
    "hematite": "raster",
    "chlorite": "raster",
    "hydromica": "raster",
    "calcite": "raster",
    "dolomite": "raster",
}
LABELS = {
    "lithology": "模拟识别岩性图",
    "faults": "模拟构造图",
    "coverage": "研究区范围",
    "rules": "本案例试用规则",
    "hematite": "赤铁矿识别结果",
    "chlorite": "绿泥石识别结果",
    "hydromica": "水云母识别结果",
    "calcite": "方解石识别结果",
    "dolomite": "白云石识别结果",
}
SEGMENTS = {"all", "lithology", "structure", "alteration"}
TITLES = {
    "check": "三要素检查与建议",
    "apply": "执行获批修正",
    "recheck": "修正后复核",
    "relations": "构造交汇重建",
    "prospect": "优先核查远景区比较",
    "final_analysis": "综合检查报告",
}
VISIBLE_OUTPUTS = {
    "check": {"issues"},
    "apply": {"lithology", "faults", "alterations", "changes"},
    "recheck": set(),
    "relations": {"intersections"},
    "prospect": {"before_zones", "after_zones", "evidence"},
}
FIELDS = (
    "rule_id",
    "rule_version",
    "knowledge_id",
    "knowledge_revision",
    "params_json",
    "rule_json",
    "units_json",
    "aliases_json",
)


def graph(segment="all"):
    initial = {key: key for key in ROLES if key != "rules"}
    initial["rules"] = "frozen_rules"
    edit = {**initial, "issues": "check/issues", "approved_changes": "approved_changes"}
    revised = {
        **initial,
        "lithology": "apply/lithology",
        "faults": "apply/faults",
        "alterations": "apply/alterations",
    }
    stages = [
        ("check", "geology-multi-check", initial),
        ("apply", "geology-multi-apply", edit),
        ("recheck", "geology-multi-check", revised),
    ]
    if segment != "lithology":
        stages.append(
            (
                "relations",
                "geology-multi-relations",
                {
                    "faults": "apply/faults",
                    "before_faults": "faults",
                    "coverage": "coverage",
                    "rules": "frozen_rules",
                },
            )
        )
    if segment in {"all", "alteration"}:
        stages.append(
            (
                "prospect",
                "geology-multi-prospect",
                {
                    **{
                        key: key
                        for key in (
                            "hematite",
                            "chlorite",
                            "hydromica",
                            "calcite",
                            "dolomite",
                        )
                    },
                    "before_lithology": "lithology",
                    "before_faults": "faults",
                    "lithology": "apply/lithology",
                    "faults": "apply/faults",
                    "alterations": "apply/alterations",
                    "intersections": "relations/intersections",
                    "coverage": "coverage",
                    "rules": "frozen_rules",
                },
            )
        )
    return stages


def validate_inputs(user, policy, inputs, parameters, selected=()):
    if not isinstance(inputs, dict) or set(inputs) != set(ROLES):
        raise ComputeError("请完整选择岩性、构造、研究区、五类矿物和本案例试用规则")
    if parameters.get("segment", "all") not in SEGMENTS:
        raise ComputeError("分段入口请选择综合、岩性、构造或蚀变")
    if set(parameters) - {
        "segment",
        "working_epsg",
        "grid_resolution_m",
        "min_zone_area_m2",
    }:
        raise ComputeError("综合推理包含未声明参数，请根据当前算法参数表重新选择")
    for key, low, high in (
        ("working_epsg", 1, 999999),
        ("grid_resolution_m", 10, 1000),
        ("min_zone_area_m2", 0, 100000000),
    ):
        if key in parameters and (
            type(parameters[key]) not in {int, float}
            or not math.isfinite(parameters[key])
            or not low <= parameters[key] <= high
            or key == "working_epsg"
            and type(parameters[key]) is not int
        ):
            raise ComputeError("综合推理参数超出有效类型或范围：" + key)
    for role, kind in ROLES.items():
        resource = resolve_resource(user, policy, inputs[role], selected)
        if resource.data_type != kind or resource.status != "active":
            raise ComputeError(LABELS[role] + "的数据类型或状态不适用")
        if (resource.source or "").startswith(
            (
                "geology-multi-reference:",
                "geology-multi-evaluation:",
                "geology-review-acceptance:",
            )
        ):
            raise PermissionDenied("评价参考资料不能作为正常推理输入")
        metadata = candidate(resource)
        if role in {"lithology", "faults", "coverage"}:
            geometry = metadata.get("geometryTypes", [])
            expected = "LineString" if role == "faults" else "Polygon"
            if not geometry or any(expected not in value for value in geometry):
                raise ComputeError(LABELS[role] + "几何类型不适用")
            fields = set(metadata["fields"])
            required = (
                {"feature_id", "name", "geo_sym"}
                if role == "lithology"
                else {"line_id"}
                if role == "faults"
                else set()
            )
            if not required <= fields:
                raise ComputeError(
                    LABELS[role] + "缺少字段：" + "、".join(sorted(required - fields))
                )
            if {"inj_id", "inj_type", "fake_type"} & fields:
                raise ComputeError("请使用去标签的中性编号运行输入")
        if kind in {"raster", "vector"} and not metadata.get("crs"):
            raise ComputeError(LABELS[role] + "缺少坐标系，无法核对空间关系")
    return read_rules(user, policy, inputs["rules"], selected)


def read_rules(user, policy, identity, selected=()):
    resource = resolve_resource(user, policy, identity, selected)
    data, info = frame(resource)
    if (
        info.get("scope") == "prefix_sample"
        or not 1 <= len(data) <= 40
        or not set(FIELDS) <= set(data.columns)
    ):
        raise ComputeError("本案例规则表须包含完整显式知识绑定、参数、单元和名称映射")
    rows = data.fillna("").to_dict(orient="records")
    try:
        bindings = [
            {
                "id": _binding_integer(row["knowledge_id"]),
                "revision": _binding_integer(row["knowledge_revision"]),
                "ruleId": str(row["rule_id"]),
                "ruleVersion": str(row["rule_version"]),
            }
            for row in rows
        ]
        units = json.loads(str(rows[0]["units_json"]))
        aliases = json.loads(str(rows[0]["aliases_json"]))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ComputeError("规则表的知识绑定或名称代号映射无效") from exc
    if (
        not isinstance(units, dict)
        or not isinstance(aliases, dict)
        or not units
        or not aliases
    ):
        raise ComputeError("冻结的地质单元及名称代号映射不能为空")
    if any(code not in units for code in aliases.values()):
        raise ComputeError("名称别名对应的地质代号不在冻结单元表中")
    entries = read_bound_rules(user, resource.project_tag_id, SCENARIO, bindings)
    return resource, entries, units, aliases


def effective_units(workflow, units, aliases):
    """A generic workflow's uploaded unit table overrides the project defaults."""
    overrides = workflow.plan.get("unitOverrides") or {}
    return (
        {**units, **overrides.get("units", {})},
        {**aliases, **overrides.get("aliases", {})},
    )


def _binding_integer(value):
    if type(value) not in {str, int, float} or (
        isinstance(value, str) and not value.strip().isdecimal()
    ):
        raise ValueError("知识绑定必须为正整数")
    number = int(value)
    if number < 1 or isinstance(value, float) and value != number:
        raise ValueError("知识绑定必须为正整数")
    return number


def prepare(workflow, user, policy):
    require_actor(user, workflow.project_tag_id, "catalog.add_dataresource")
    if workflow.plan.get("knowledgeSelection", {}).get("mode") == "none":
        raise ComputeError("本案例需要读取显式绑定的试用知识，请启用地质知识依据")
    resource, entries, units, aliases = validate_inputs(
        user,
        policy,
        workflow.plan["inputs"],
        workflow.parameters,
        workflow.resource_ids,
    )
    units, aliases = effective_units(workflow, units, aliases)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    bindings = []
    for index, entry in enumerate(entries):
        bound = entry["trialBinding"]
        config = entry["ruleConfig"]
        writer.writerow(
            {
                "rule_id": bound["ruleId"],
                "rule_version": bound["ruleVersion"],
                "knowledge_id": entry["id"],
                "knowledge_revision": entry["revision"],
                "params_json": json.dumps(config["parameters"], ensure_ascii=False),
                "rule_json": json.dumps(config["rule"], ensure_ascii=False),
                "units_json": json.dumps(units, ensure_ascii=False)
                if index == 0
                else "",
                "aliases_json": json.dumps(aliases, ensure_ascii=False)
                if index == 0
                else "",
            }
        )
        bindings.append(
            {key: bound[key] for key in ("id", "revision", "ruleId", "ruleVersion")}
            | {
                "title": entry["title"],
                "parameters": config["parameters"],
            }
        )
    raw = stream.getvalue().encode("utf-8")
    relative = f"demo/workflows/{workflow.id}/trial-rules.csv"
    path = table_data_path(relative)
    source = f"geology-multi-frozen-rules:{workflow.id}"
    with transaction.atomic():
        existing = DataResource.objects.filter(source=source).first()
        if existing:
            if not path.is_file() or path.read_bytes() != raw:
                raise ComputeError("已冻结的试用规则与当前知识版本不一致", 409)
            frozen = resolve_resource(user, policy, existing.id)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            frozen = DataResource.objects.create(
                project_tag_id=workflow.project_tag_id,
                name="本案例试用规则运行版本",
                code=f"multi-rules-{workflow.id.hex}",
                data_type="table",
                file_format="CSV",
                storage_path="table/" + relative,
                source=source,
                owner_only=True,
                maintainer=user,
                size_bytes=len(raw),
                item_count=len(entries),
                is_compute_result=True,
            )
    workflow.plan.update(
        frozen_rules=frozen.id,
        trialRuleBindings=bindings,
        trialRulesDigest=digest(entries),
        trialRulesSnapshot={
            "resourceId": resource.id,
            "revision": resource.updated_at.isoformat(),
            "contentDigest": digest([entries, units, aliases]),
            "frozenChecksum": checksum(path),
        },
        multiGraph=graph(workflow.parameters.get("segment", "all")),
        upstreamVersions={
            key: {
                "resourceId": identity,
                "revision": resolve_resource(
                    user, policy, identity
                ).updated_at.isoformat(),
            }
            for key, identity in workflow.plan["inputs"].items()
        },
    )
    return (
        entries
        + search_entries(
            user, "地质 岩性 构造 蚀变 条件 例外", limit=4, domains=["geology"]
        )["items"]
    )


def authorize_frozen(workflow, user, policy):
    source, entries, units, aliases = read_rules(
        user, policy, workflow.plan["inputs"]["rules"]
    )
    units, aliases = effective_units(workflow, units, aliases)
    stored = workflow.plan["trialRulesSnapshot"]
    path = table_data_path(f"demo/workflows/{workflow.id}/trial-rules.csv")
    resolve_resource(user, policy, workflow.plan["frozen_rules"])
    if (
        stored["revision"] != source.updated_at.isoformat()
        or stored["contentDigest"] != digest([entries, units, aliases])
        or not path.is_file()
        or checksum(path) != stored["frozenChecksum"]
    ):
        raise PermissionDenied("本次知识、规则参数或冻结运行文件已变化，请重新生成计划")
