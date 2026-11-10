"""Use the common preparation queue at operator-to-operator boundaries too."""

import hashlib

from apps.agent.workflow_resources import resolve_workflow_resource
from apps.compute.data import list_candidate
from apps.compute.packages import ComputeError
from .script_bridges import choose_bridge, planned_script, versions
from .state import emit


def prepare(workflow, user, policy, node, version, inputs):
    settings = workflow.plan.get("inputPreparationPolicy", {})
    if not settings.get("allowScripts"):
        return inputs
    specs = {item["key"]: item for item in version.manifest["inputs"]}
    parameters = {
        **node.get("parameters", {}),
        **workflow.parameters.get("nodeParameters", {}).get(node["id"], {}),
    }
    ready = workflow.plan.setdefault("preparedNodeInputs", {}).setdefault(
        node["id"], {}
    )
    schemas = workflow.plan.setdefault("inputPreparationSchemas", {})
    result, pending = {}, False
    for key, identities in inputs.items():
        if key in ready:
            resource = resolve_workflow_resource(user, policy, ready[key], workflow)
            result[key] = resource.pk
            continue
        identities = identities if isinstance(identities, list) else [identities]
        resources = [
            resolve_workflow_resource(user, policy, identity, workflow)
            for identity in identities
        ]
        spec = specs[key]
        required = [
            parameters.get(item["key"], item.get("default"))
            for item in version.manifest["parameters"]
            if item["type"] == "field" and item.get("input") == key
        ]
        required = [name for name in required if isinstance(name, str)]
        direct = len(resources) == 1 and resources[0].data_type == spec["kind"]
        if direct and (required or spec.get("minBands") or spec.get("geometryTypes")):
            resource = resources[0]
            identity = str(resource.pk) + ":" + resource.updated_at.isoformat()
            if identity not in schemas:
                schemas[identity] = list_candidate(resource)
            metadata = schemas[identity]
            direct = (
                set(required) <= set(metadata["fields"])
                and metadata["bands"] >= spec.get("minBands", 0)
                and (
                    not spec.get("geometryTypes")
                    or set(metadata["geometryTypes"]) <= set(spec["geometryTypes"])
                )
            )
        if direct:
            result[key] = resources[0].pk
            continue
        role = (
            "node-" + hashlib.sha256((node["id"] + ":" + key).encode()).hexdigest()[:24]
        )
        entries = workflow.plan.setdefault("inputAdaptations", [])
        entry = next((row for row in entries if row["role"] == role), None)
        if entry is None:
            bridge = choose_bridge(
                user,
                [row.data_type for row in resources],
                [spec["kind"]],
                available=versions(permitted=settings.get("algorithmVersionIds")),
            )
            if bridge is None:
                raise ComputeError(
                    "节点输入需要衔接，但没有当前授权范围可用的受限解释器："
                    + node["title"]
                    + "/"
                    + key
                )
            planning = planned_script(bridge)
            if planning["status"] != "needs_script":
                raise ComputeError(planning["script"]["summary"])
            first = resources[0]
            entry = {
                "role": role,
                "nodeId": node["id"],
                "nodeInputKey": key,
                "sourceId": first.pk,
                "sourceName": "、".join(row.name for row in resources)[:250],
                "sourceType": first.data_type,
                "sourceRevision": first.updated_at.isoformat(),
                "sources": [
                    {"id": row.pk, "revision": row.updated_at.isoformat()}
                    for row in resources
                ],
                "sourceIds": [row.pk for row in resources],
                "targetTypes": [spec["kind"]],
                "targetSemantics": "",
                "targetContract": {
                    "dataTypes": [spec["kind"]],
                    "requiredFields": required,
                    "description": node["description"]
                    + "；"
                    + node.get("instruction", ""),
                    "minBands": spec.get("minBands", 0),
                    "geometryTypes": spec.get("geometryTypes", []),
                },
                **planning,
            }
            entries.append(entry)
            workflow.resource_ids = sorted(
                set(workflow.resource_ids) | {row.pk for row in resources}
            )
        pending = True
        workflow.plan.pop("inputAdaptationComplete", None)
    if pending:
        workflow.status = "queued"
        emit(
            workflow,
            "executor",
            node["id"],
            "preparing_inputs",
            "智能体将先衔接当前节点所需资料，完成后继续固定算子",
        )
        return None
    return result
