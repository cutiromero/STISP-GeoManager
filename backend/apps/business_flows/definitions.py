"""Bounded declarative scientific flows, without executable source or paths."""

import hashlib
import json
import re

from django.core.exceptions import ValidationError

# Configuration: scientific flow definitions remain small and bounded.
MAX_NODES = 32
MAX_ROLES = 30
MAX_REVISIONS = 3
MAX_DEFINITION_BYTES = 128 * 1024
CODE_PATTERN = re.compile(r"[a-z][a-z0-9_-]{1,79}\Z")
NODE_PATTERN = re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
DATA_TYPES = {"vector", "raster", "table", "gene", "document", "image"}
NODE_KINDS = {"agent", "operator", "human", "result"}
ADAPTERS = {"geology_generic", "research_flow"}


def invalid(detail):
    raise ValidationError(detail)


def text(value, name, maximum, *, empty=False):
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not empty and not value.strip())
    ):
        invalid(f"{name}格式或长度无效")
    return value.strip()


def keys(value, allowed, name):
    if not isinstance(value, dict) or set(value) - set(allowed):
        invalid(f"{name}包含未知字段或不是对象")


def strings(value, name, maximum=80):
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 160
            for item in value
        )
    ):
        invalid(f"{name}必须是有界字符串列表")
    if len(set(value)) != len(value):
        invalid(f"{name}不得重复")
    return value


def node_roles(node):
    return list(
        dict.fromkeys(
            [
                *node["dataRoles"],
                *[
                    row["role"]
                    for row in node.get("inputBindings", {}).values()
                    if "role" in row
                ],
            ]
        )
    )


def normalize_definition(value):
    keys(
        value,
        {
            "schemaVersion",
            "adapter",
            "inputRequirements",
            "nodes",
            "outputRequirements",
            "inputPreparation",
            "skill",
            "executionMode",
        },
        "流程定义",
    )
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        invalid("流程定义不是有效JSON")
    if len(encoded) > MAX_DEFINITION_BYTES:
        invalid("流程定义超过128KiB限制")
    if (
        type(value.get("schemaVersion")) is not int
        or value["schemaVersion"] != 1
        or not isinstance(value.get("adapter"), str)
        or value.get("adapter") not in ADAPTERS
    ):
        invalid("流程定义版本或执行适配器无效")
    result = json.loads(encoded)
    if not isinstance(result.get("executionMode", "nodes"), str) or result.get(
        "executionMode", "nodes"
    ) not in {"nodes", "main_agent"}:
        invalid("业务流执行方式须为nodes或main_agent")
    if "inputPreparation" in result:
        from .input_policy import validate

        result["inputPreparation"] = validate(result["inputPreparation"])
    inputs = result.get("inputRequirements", [])
    nodes = result.get("nodes", [])
    if not isinstance(inputs, list) or len(inputs) > MAX_ROLES:
        invalid("输入资料角色最多30项")
    roles = set()
    for item in inputs:
        keys(
            item,
            {
                "key",
                "label",
                "description",
                "dataTypes",
                "required",
                "requiredFields",
                "multiple",
                "semanticType",
            },
            "输入规范",
        )
        role = text(item.get("key"), "资料角色", 64)
        if not NODE_PATTERN.fullmatch(role) or role in roles:
            invalid("资料角色编码无效或重复")
        roles.add(role)
        item["label"] = text(item.get("label"), "资料角色名称", 120)
        item["description"] = text(
            item.get("description", ""), "资料规范说明", 1500, empty=True
        )
        types = strings(item.get("dataTypes", []), "资料类型", 6)
        if not types or set(types) - DATA_TYPES:
            invalid("必须选择平台支持的资料类型")
        if type(item.get("required", False)) is not bool:
            invalid("资料必选标记必须是布尔值")
        item["required"] = item.get("required", False)
        item["requiredFields"] = strings(item.get("requiredFields", []), "必需字段")
        if "multiple" in item and type(item["multiple"]) is not bool:
            invalid("多来源标记必须为布尔值")
        if "semanticType" in item:
            item["semanticType"] = text(item["semanticType"], "目标输入语义", 100)
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_NODES:
        invalid("业务流必须包含1至32个节点")
    node_ids = set()
    for node in nodes:
        keys(
            node,
            {
                "id",
                "title",
                "description",
                "kind",
                "dependsOn",
                "dataRoles",
                "algorithmVersionId",
                "instruction",
                "parameters",
                "inputBindings",
                "review",
                "contract",
                "allowSkip",
            },
            "流程节点",
        )
        identity = text(node.get("id"), "节点编码", 64)
        if not NODE_PATTERN.fullmatch(identity) or identity in node_ids:
            invalid("节点编码无效或重复")
        node_ids.add(identity)
        node["title"] = text(node.get("title"), "节点名称", 120)
        node["description"] = text(
            node.get("description", ""), "节点说明", 2000, empty=True
        )
        node["instruction"] = text(
            node.get("instruction", ""), "节点任务说明", 12000, empty=True
        )
        if not isinstance(node.get("kind"), str) or node.get("kind") not in NODE_KINDS:
            invalid("未知节点类型")
        if "allowSkip" in node and type(node["allowSkip"]) is not bool:
            invalid("allowSkip必须为布尔值")
        if "contract" in node:
            if node["kind"] != "agent" or result["adapter"] != "research_flow":
                invalid("仅通用智能体节点可声明执行合同")
            from .node_contracts import normalize_contract

            node["contract"] = normalize_contract(node["contract"])
            if result.get("executionMode") == "main_agent":
                contract = node["contract"]
                tools = set(contract["tools"])
                if "run_operator" in tools and (
                    not {"operator_catalog", "preflight_operator"} <= tools
                    or not contract["maxOperatorCalls"]
                ):
                    invalid("计算合同须允许算子查询、预检并保留实际算子额度")
                if (
                    any(
                        row["semanticType"] != "analysis"
                        for row in contract["requiredOutputs"]
                    )
                    and "run_operator" not in tools
                ):
                    invalid("非分析成果合同须允许真实算子执行，不能仅凭文字完成")
        node["dependsOn"] = strings(node.get("dependsOn", []), "节点依赖", MAX_NODES)
        node["dataRoles"] = strings(
            node.get("dataRoles", []), "节点资料角色", MAX_ROLES
        )
        if set(node["dataRoles"]) - roles:
            invalid("节点引用了未定义的资料角色")
        if "parameters" in node:
            if node["kind"] != "operator" or result["adapter"] != "research_flow":
                invalid("仅通用业务流算子节点可指定参数默认值")
            if not isinstance(node["parameters"], dict) or len(node["parameters"]) > 50:
                invalid("算子参数默认值必须是最多50键的对象")

            def bounded(item, depth=0):
                if depth > 8:
                    invalid("算子参数嵌套过深")
                if isinstance(item, dict):
                    if len(item) > 50 or any(
                        not isinstance(key, str)
                        or len(key) > 160
                        or key.startswith("_")
                        for key in item
                    ):
                        invalid("算子参数键无效或包含内部状态")
                    for child in item.values():
                        bounded(child, depth + 1)
                elif isinstance(item, list):
                    if len(item) > 1000:
                        invalid("算子参数列表过长")
                    for child in item:
                        bounded(child, depth + 1)

            bounded(node["parameters"])
        if "inputBindings" in node:
            if node["kind"] != "operator" or result["adapter"] != "research_flow":
                invalid("只有通用业务流算子节点可声明算子输入连线")
            bindings = node["inputBindings"]
            if not isinstance(bindings, dict) or len(bindings) > MAX_ROLES:
                invalid("算子输入连线必须是最多30键的对象")
            for name, source in bindings.items():
                if (
                    not isinstance(name, str)
                    or not 1 <= len(name) <= 80
                    or name != name.strip()
                ):
                    invalid("算子输入连线键无效")
                if not isinstance(source, dict):
                    invalid("输入连线来源必须是对象")
                if set(source) == {"role"}:
                    if (
                        not isinstance(source["role"], str)
                        or source["role"] not in roles
                    ):
                        invalid("输入连线引用了未声明的资料角色")
                elif set(source) == {"nodeId", "outputKey"}:
                    if (
                        not isinstance(source["nodeId"], str)
                        or not isinstance(source["outputKey"], str)
                        or not 1 <= len(source["outputKey"]) <= 80
                        or source["outputKey"] != source["outputKey"].strip()
                    ):
                        invalid("输入连线的前序节点或输出键无效")
                else:
                    invalid("输入连线必须只选择资料角色或前序算子输出，不能混合来源")
        algorithm = node.get("algorithmVersionId")
        if algorithm is not None and (type(algorithm) is not int or algorithm < 1):
            invalid("算子版本编号无效")
        if (
            result["adapter"] == "research_flow"
            and node["kind"] != "operator"
            and algorithm is not None
        ):
            invalid("仅算子节点可以绑定算法版本")
        if (
            node["kind"] == "operator"
            and result["adapter"] == "research_flow"
            and algorithm is None
        ):
            invalid("通用业务流的算子节点必须绑定已发布算子版本")
        review = node.setdefault(
            "review", {"ai": False, "human": node["kind"] == "human", "maxRevisions": 0}
        )
        keys(review, {"ai", "human", "maxRevisions", "model"}, "节点审核设置")
        if any(type(review.get(name, False)) is not bool for name in ("ai", "human")):
            invalid("审核启用标记必须是布尔值")
        review.setdefault("ai", False)
        review.setdefault("human", node["kind"] == "human")
        revisions = review.setdefault("maxRevisions", 1 if review["ai"] else 0)
        if type(revisions) is not int or not 0 <= revisions <= MAX_REVISIONS:
            invalid("返修次数必须为0至3")
        if node["kind"] == "human" and not review["human"]:
            invalid("人工节点必须保留人工决定，不能交给AI代替")
        if "model" in review:
            review["model"] = text(review["model"], "审核模型", 80)
    by_id = {node["id"]: node for node in nodes}
    done, visiting = set(), set()

    def visit(identity):
        if identity in visiting:
            invalid("流程依赖存在环；返修请使用有界maxRevisions")
        if identity in done:
            return
        visiting.add(identity)
        for parent in by_id[identity]["dependsOn"]:
            if parent not in by_id:
                invalid("节点依赖不存在")
            visit(parent)
        visiting.remove(identity)
        done.add(identity)

    for identity in node_ids:
        visit(identity)
    ancestors_cache = {}

    def ancestors(identity):
        if identity not in ancestors_cache:
            found = set()
            for dependency in by_id[identity]["dependsOn"]:
                found.add(dependency)
                found.update(ancestors(dependency))
            ancestors_cache[identity] = found
        return ancestors_cache[identity]

    for node in nodes:
        for source in node.get("inputBindings", {}).values():
            if "nodeId" not in source:
                continue
            upstream = source["nodeId"]
            if (
                upstream == node["id"]
                or upstream not in by_id
                or upstream not in ancestors(node["id"])
            ):
                invalid(
                    "算子输出连线必须来自当前节点的前序依赖祖先，不能自指、引用未知或未来节点"
                )
            if by_id[upstream]["kind"] != "operator" and not by_id[upstream].get(
                "contract"
            ):
                invalid("输入连线只可引用前序算子的真实输出")
    if result["adapter"] == "geology_generic":
        from .builtins import GEOLOGY_CURRENT_ROLES, GEOLOGY_NODES, GEOLOGY_ROLES

        input_roles = {item["key"] for item in inputs}
        if input_roles not in (
            set(GEOLOGY_CURRENT_ROLES),
            set(GEOLOGY_ROLES),
            set(GEOLOGY_ROLES) - {"alterations"},
        ):
            invalid("逻辑推理资料角色必须与专业流程一致")

        if [node["id"] for node in nodes] != [row[0] for row in GEOLOGY_NODES]:
            invalid("逻辑推理使用已登记的专业流程骨架，不能增删或重排节点")
        for index, (identity, _title, kind, expected_roles) in enumerate(GEOLOGY_NODES):
            node = nodes[index]
            expected_kind = {kind, "agent"} if identity == "finish" else {kind}
            if (
                node["kind"] not in expected_kind
                or node["dependsOn"] != ([GEOLOGY_NODES[index - 1][0]] if index else [])
                or node["dataRoles"]
                != [role for role in expected_roles if role in input_roles]
                or node.get("algorithmVersionId") is not None
            ):
                invalid("逻辑推理的节点类型、资料角色和算子绑定由专业适配器管理")
            if node["review"]["human"] != (identity in {"inputs", "apply"}):
                invalid("专业流程的人工决定固定为资料确认和处置批准，不能由图配置增删")
            if identity not in {"apply", "finish"} and node["review"]["ai"]:
                invalid("专业流程独立AI审核仅适用于处置建议和成果整理的实际决策边界")
        for item in inputs:
            if item["key"] == "alterations" and (
                item.get("multiple") is not True
                or item.get("semanticType") != "class_mask_stack_v1"
            ):
                invalid("专业分类集合须保留多来源和命名类别掩膜规范")
            if item["dataTypes"] != [GEOLOGY_ROLES[item["key"]][1]] or (
                item["key"] == "lithology" and not item["required"]
            ):
                invalid("逻辑推理资料类型或必需岩性图规范无效")
    if "skill" in result:
        from .execution_session import normalize_skill

        result["skill"] = normalize_skill(result["skill"], node_ids)
    result["inputRequirements"] = inputs
    result["nodes"] = nodes
    result["outputRequirements"] = strings(
        result.get("outputRequirements", []), "成果规范", 30
    )
    return result


def definition_hash(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
