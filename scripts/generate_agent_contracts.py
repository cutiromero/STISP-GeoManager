"""从唯一OpenAPI契约生成Agent工具合同；默认生成，--check只核对。"""

import argparse
import ast
import json
from pathlib import Path
import re

import yaml

# CONFIGURATION
ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/openapi.yaml"
REGISTRY = ROOT / "backend/apps/agent/tools.py"
OUTPUT = ROOT / "backend/apps/agent/tool_contracts.json"
EFFECTS = {
    "read",
    "draft",
    "compute",
    "import",
    "export",
    "control",
    "publish",
    "share",
}


def validate_schema(schema, tool, path=()):
    supported = {
        "type",
        "description",
        "title",
        "default",
        "examples",
        "example",
        "deprecated",
        "readOnly",
        "writeOnly",
        "properties",
        "additionalProperties",
        "required",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "maxProperties",
        "enum",
        "const",
        "oneOf",
        "anyOf",
        "x-business-validation",
    }
    if not isinstance(schema, dict) or set(schema) - supported:
        raise ValueError(f"工具{tool}使用了未支持的参数schema关键字")
    if schema.get("format") not in {None, "uuid", "date-time"}:
        raise ValueError(f"工具{tool}使用了未支持的格式校验")
    if schema.get("x-business-validation") and not (
        tool == "execute_operator" and path in {("inputs",), ("parameters",)}
    ):
        raise ValueError("动态清单校验只允许固定算子输入和参数信封")
    for name, child in schema.get("properties", {}).items():
        validate_schema(child, tool, (*path, name))
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            validate_schema(schema[key], tool, path)
    for key in ("oneOf", "anyOf"):
        for child in schema.get(key, []):
            validate_schema(child, tool, path)


def registrations(source):
    result = {}
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ToolSpec"
        ):
            values = [ast.literal_eval(value) for value in node.args]
            name, capability, description, arguments = values
            if name in result:
                raise ValueError(f"重复工具：{name}")
            result[name] = (capability, description, arguments)
    return result


def generate(spec, registered):
    schemas = spec["components"]["schemas"]
    operations = {
        operation["operationId"]
        for path in spec["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    declarations = spec["x-agent-tools"]
    if set(declarations) != set(registered):
        raise ValueError("OpenAPI工具声明与实际注册表不一致")

    def resolve(value, parents=()):
        if isinstance(value, list):
            return [resolve(item, parents) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            prefix = "#/components/schemas/"
            reference = value["$ref"]
            if not reference.startswith(prefix) or reference in parents:
                raise ValueError("工具参数只允许无环的本地schema引用")
            return resolve(
                {
                    **schemas[reference[len(prefix) :]],
                    **{k: v for k, v in value.items() if k != "$ref"},
                },
                (*parents, reference),
            )
        return {key: resolve(item, parents) for key, item in value.items()}

    result = {}
    for name, declaration in declarations.items():
        capability, description, arguments = registered[name]
        if not re.fullmatch(r"\d+\.\d+\.\d+", declaration.get("version", "")):
            raise ValueError(f"工具{name}缺少有效语义版本")
        for key in ("requiredPermissions", "anyPermissions"):
            if not isinstance(declaration.get(key), list) or any(
                not isinstance(item, str) or not re.fullmatch(r"[a-z_]+\.[a-z_]+", item)
                for item in declaration[key]
            ):
                raise ValueError(f"工具{name}权限声明无效")
        schema = resolve(declaration["inputSchema"])
        validate_schema(schema, name)
        if (
            schema.get("type") != "object"
            or schema.get("additionalProperties") is not False
        ):
            raise ValueError(f"工具{name}必须拒绝未知顶层参数")
        if set(schema.get("properties", {})) != set(arguments):
            raise ValueError(f"工具{name}参数与注册表不一致")
        if not set(schema.get("required", ())) <= set(arguments):
            raise ValueError(f"工具{name}必填参数不存在")
        if declaration["effect"] not in EFFECTS or declaration["risk"] not in {
            "low",
            "medium",
            "high",
        }:
            raise ValueError(f"工具{name}影响或风险分类无效")
        implementation = declaration.get("implementation")
        if implementation not in {"shared_service", "internal_service"}:
            raise ValueError(f"工具{name}未说明共享业务服务或内部工具实现")
        if (
            implementation == "shared_service" and not declaration["operationIds"]
        ) or not set(declaration["operationIds"]) <= operations:
            raise ValueError(f"工具{name}引用了不存在的业务接口")
        if declaration["approval"] not in {
            "none",
            "authorized_scope",
            "explicit_request",
            "human_decision",
        }:
            raise ValueError(f"工具{name}授权方式无效")
        for field in ("idempotency", "retry", "completion", "limitations"):
            if (
                not isinstance(declaration.get(field), str)
                or not declaration[field].strip()
            ):
                raise ValueError(f"工具{name}缺少{field}说明")
        result[name] = {
            **declaration,
            "name": name,
            "capability": capability,
            "description": description,
            "inputSchema": schema,
        }
    return {"schemaVersion": 1, "tools": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    value = generate(
        yaml.safe_load(SPEC.read_text()), registrations(REGISTRY.read_text())
    )
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text() != content:
            raise SystemExit(
                "Agent合同未生成或与OpenAPI不一致，请运行scripts/generate_agent_contracts.py"
            )
    else:
        OUTPUT.write_text(content)
    print(
        f"Agent工具合同{'核对' if args.check else '生成'}通过：{len(value['tools'])}项"
    )


if __name__ == "__main__":
    main()
