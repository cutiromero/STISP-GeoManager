"""算子语义清单的纯校验；不导入上传的代码。"""

from copy import deepcopy
import math
from pathlib import PurePosixPath
import re

from .packages import ComputeError, EXTENSIONS, KEY, clean_text

OPERATIONS = {"check", "correct", "convert", "statistics", "infer", "map"}
REMEDIES = {
    "adjust_parameters",
    "convert_input",
    "complete_mapping",
    "replace_data",
    "human_review",
    "unrecoverable",
}
FIELD_TYPES = {"string", "integer", "number", "boolean", "datetime"}
PRERELEASE = r"(?:0|[1-9]\d*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER = rf"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-{PRERELEASE}(?:\.{PRERELEASE})*)?"


def object_keys(value, allowed, required, path):
    if (
        not isinstance(value, dict)
        or set(value) - set(allowed)
        or set(required) - set(value)
    ):
        raise ComputeError(
            f"{path} 字段不完整或含未知字段；必需：{', '.join(required)}"
        )


def text(value, path, maximum=2000):
    return clean_text(value, maximum, path)


def choices(value, allowed, path, maximum=32):
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= maximum
        or any(not isinstance(item, str) or item not in allowed for item in value)
        or len(value) != len(set(value))
    ):
        raise ComputeError(
            f"{path} 须为不重复的受控词列表：{', '.join(sorted(allowed))}"
        )


def boolean(value, path):
    if type(value) is not bool:
        raise ComputeError(path + " 须为布尔值")


def fields(value, path, *, output=False):
    if not isinstance(value, list) or len(value) > 100:
        raise ComputeError(path + " 须为至多100项的字段列表")
    seen = set()
    for item in value:
        object_keys(
            item,
            {
                "role",
                "description",
                "types",
                "unit",
                "min",
                "max",
                "required",
                "parameter",
                "name",
                "legacyName",
            },
            {"role", "description", "types", "required"},
            path,
        )
        role = item["role"]
        if not isinstance(role, str) or not KEY.fullmatch(role) or role in seen:
            raise ComputeError(path + ".role 须为唯一语义角色标识")
        seen.add(role)
        text(item["description"], path + ".description")
        choices(item["types"], FIELD_TYPES, path + ".types")
        boolean(item["required"], path + ".required")
        for key in ("unit", "parameter", "name", "legacyName"):
            if key in item:
                text(item[key], path + "." + key, 160)
        if (
            not output
            and "name" in item
            or output
            and ("parameter" in item or "legacyName" in item)
        ):
            raise ComputeError(path + " 输入按角色映射，输出可声明实际字段名")
        for bound in ("min", "max"):
            if bound in item and (
                type(item[bound]) not in {int, float} or not math.isfinite(item[bound])
            ):
                raise ComputeError(path + "." + bound + " 须为有限数字")
        if item.get("min", -math.inf) > item.get("max", math.inf):
            raise ComputeError(path + " 最小值不能大于最大值")
        if ("min" in item or "max" in item) and not set(item["types"]) <= {
            "number",
            "integer",
        }:
            raise ComputeError(path + " 取值范围只适用于数值字段")


def safe_relative(value, path):
    if (
        not isinstance(value, str)
        or len(value) > 160
        or not value
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or PurePosixPath(value).is_absolute()
        or ".." in PurePosixPath(value).parts
        or any(part.startswith(".") for part in PurePosixPath(value).parts)
    ):
        raise ComputeError(path + " 须为包内相对路径，不允许链接或父路径")


def capability_description(value):
    object_keys(
        value,
        {"operations", "dataTypes", "summary", "useWhen", "avoidWhen"},
        {"operations", "dataTypes", "summary", "useWhen", "avoidWhen"},
        "capabilities",
    )
    choices(value["operations"], OPERATIONS, "capabilities.operations")
    choices(value["dataTypes"], set(EXTENSIONS), "capabilities.dataTypes")
    for key in ("summary", "useWhen", "avoidWhen"):
        text(value[key], "capabilities." + key)
    return deepcopy(value)


def validate_semantics(result, manifest):
    strict = result["schemaVersion"] == 2
    if not strict:
        if "capabilities" in manifest:
            try:
                result["capabilities"] = capability_description(
                    manifest["capabilities"]
                )
            except (ComputeError, TypeError, KeyError):
                pass
        return
    if strict:
        if "deterministic" in manifest:
            boolean(manifest["deterministic"], "deterministic")
        unknown = set(manifest) - {
            "schemaVersion",
            "identifier",
            "name",
            "version",
            "description",
            "author",
            "runtime",
            "deterministic",
            "agent",
            "qualityReport",
            "inputs",
            "parameters",
            "outputs",
            "timeoutSeconds",
            "inputAdapter",
            "inputScriptBridge",
            "capabilities",
            "errors",
            "resources",
            "selfTests",
        }
        if unknown:
            raise ComputeError("第2版清单含未知字段：" + ", ".join(sorted(unknown)))
        allowed = {
            "inputs": {
                "key",
                "label",
                "kind",
                "required",
                "minBands",
                "raster",
                "geometryTypes",
                "description",
                "fields",
                "crs",
                "spatial",
                "repeat",
            },
            "parameters": {
                "key",
                "label",
                "type",
                "required",
                "default",
                "min",
                "max",
                "choices",
                "input",
                "help",
                "when",
                "maxLength",
                "agent",
            },
            "outputs": {
                "key",
                "label",
                "kind",
                "file",
                "required",
                "description",
                "fields",
                "final",
            },
        }
        for section in allowed:
            for item in manifest.get(section, []):
                if set(item) - allowed[section]:
                    raise ComputeError(section + "." + item["key"] + " 含未知字段")
                if "required" in item:
                    boolean(item["required"], section + ".required")
    if not re.fullmatch(SEMVER, result["version"]):
        raise ComputeError("第2版 version 须为语义化版本号，如1.1.0")
    result["capabilities"] = capability_description(manifest.get("capabilities"))
    inputs = {item["key"]: item for item in result["inputs"]}
    parameters = {item["key"]: item for item in result["parameters"]}
    for item in result["inputs"]:
        path = "inputs." + item["key"]
        if "raster" in item:
            from .raster_contracts import validate_contract

            if item["kind"] != "raster":
                raise ComputeError("栅格合同只能用于栅格端口")
            validate_contract(item["raster"])
        if strict or "fields" in item:
            fields(item.get("fields"), path + ".fields")
            legacy_names = [
                field["legacyName"] for field in item["fields"] if "legacyName" in field
            ]
            if (
                len(legacy_names) != len(set(legacy_names))
                or legacy_names
                and item["kind"] not in {"vector", "table"}
            ):
                raise ComputeError(path + " legacyName须唯一且仅用于矢量/表格")
            for role in item["fields"]:
                parameter = role.get("parameter")
                if parameter and "repeat" in item:
                    raise ComputeError(path + " 集合字段映射不得关联单值参数")
                if parameter and (
                    parameter not in parameters
                    or parameters[parameter].get("input") != item["key"]
                    or parameters[parameter]["type"] not in {"field", "band"}
                ):
                    raise ComputeError(
                        path + " 角色parameter须引用该输入的field/band参数"
                    )
        if strict or "description" in item:
            text(item.get("description"), path + ".description")
        if strict or "crs" in item:
            crs = item.get("crs")
            object_keys(crs, {"mode", "input"}, {"mode"}, path + ".crs")
            if crs["mode"] not in {"any", "projected", "same_as"}:
                raise ComputeError(path + ".crs.mode 无效")
            if crs["mode"] == "same_as":
                if crs.get("input") not in inputs or crs["input"] == item["key"]:
                    raise ComputeError(path + ".crs.input 须引用其他输入")
            elif "input" in crs:
                raise ComputeError(path + ".crs.input 仅用于same_as")
        if "spatial" in item:
            spatial = item["spatial"]
            object_keys(
                spatial, {"relation", "input"}, {"relation", "input"}, path + ".spatial"
            )
            if (
                spatial["relation"] not in {"intersects", "within"}
                or spatial["input"] not in inputs
                or spatial["input"] == item["key"]
            ):
                raise ComputeError(path + ".spatial 须声明intersects/within与其他输入")
        for reference in (
            item.get("crs", {}).get("input"),
            item.get("spatial", {}).get("input"),
        ):
            if reference and "repeat" in inputs[reference]:
                raise ComputeError(path + " 坐标系与范围参照须为单个输入")
        if "repeat" in item:
            repeat = item["repeat"]
            object_keys(
                repeat,
                {"min", "max", "labelRequired"},
                {"min", "max", "labelRequired"},
                path + ".repeat",
            )
            if (
                type(repeat["min"]) is not int
                or type(repeat["max"]) is not int
                or not 0 <= repeat["min"] <= repeat["max"] <= 64
            ):
                raise ComputeError(path + ".repeat 数量须满足0≤min≤max≤64")
            boolean(repeat["labelRequired"], path + ".repeat.labelRequired")
            if item["required"] and repeat["min"] < 1:
                raise ComputeError(path + " 必需集合的min至少为1")
    for item in result["parameters"]:
        if item["type"] in {"field", "band"} and "repeat" in inputs[item["input"]]:
            raise ComputeError("集合输入的字段/波段须通过成员映射读取，不使用单值参数")
        if strict or "agent" in item:
            text(item.get("help"), "parameters." + item["key"] + ".help")
            agent = item.get("agent")
            object_keys(
                agent,
                {"adjustable", "advice"},
                {"adjustable", "advice"},
                "parameter.agent",
            )
            boolean(agent["adjustable"], "parameter.agent.adjustable")
            text(agent["advice"], "parameter.agent.advice")
        if strict and "default" in item:
            from .services import parameter_values

            probe = deepcopy(item)
            probe.pop("when", None)
            if probe["type"] in {"field", "band"}:
                probe["type"] = "string" if probe["type"] == "field" else "integer"
            parameter_values(
                {"parameters": [probe]}, {}, {probe["key"]: probe["default"]}
            )
    for item in result["outputs"]:
        if strict and item["file"].startswith(("__operator_", "__platform_")):
            raise ComputeError("输出文件不得占用平台协议保留名称")
        if strict or "description" in item:
            text(item.get("description"), "outputs." + item["key"] + ".description")
            fields(
                item.get("fields"), "outputs." + item["key"] + ".fields", output=True
            )
            boolean(item.get("final"), "outputs." + item["key"] + ".final")
    errors = manifest.get("errors")
    if not isinstance(errors, list) or not 1 <= len(errors) <= 64:
        raise ComputeError("errors 须为1至64项错误码表")
    seen = set()
    for error in errors:
        object_keys(
            error,
            {"code", "meaning", "remedy", "precondition"},
            {"code", "meaning", "remedy", "precondition"},
            "errors",
        )
        code = error["code"]
        if (
            not isinstance(code, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code)
            or code.startswith("PLATFORM_")
            or code in seen
        ):
            raise ComputeError("errors.code 须唯一、全大写，且不得使用PLATFORM_前缀")
        seen.add(code)
        if error["remedy"] not in REMEDIES:
            raise ComputeError("errors.remedy 补救类别无效")
        text(error["meaning"], "errors.meaning")
        text(error["precondition"], "errors.precondition")
    resources = manifest.get("resources")
    object_keys(
        resources,
        {"duration", "memory", "scaling"},
        {"duration", "memory", "scaling"},
        "resources",
    )
    if resources["duration"] not in {"seconds", "minutes", "hours"} or resources[
        "memory"
    ] not in {"small", "medium", "large"}:
        raise ComputeError("resources 须声明seconds/minutes/hours及small/medium/large")
    text(resources["scaling"], "resources.scaling")
    tests = manifest.get("selfTests")
    if not isinstance(tests, list) or not 1 <= len(tests) <= 10:
        raise ComputeError("selfTests 须包含1至10组小样例")
    names = set()
    for test in tests:
        object_keys(
            test,
            {"name", "fixture", "expect"},
            {"name", "fixture", "expect"},
            "selfTests",
        )
        text(test["name"], "selfTests.name", 80)
        if test["name"] in names:
            raise ComputeError("selfTests.name 不得重复")
        names.add(test["name"])
        safe_relative(test["fixture"], "selfTests.fixture")
        expect = test["expect"]
        object_keys(expect, {"files", "errorCode"}, (), "selfTests.expect")
        if bool(expect.get("files")) == bool(expect.get("errorCode")):
            raise ComputeError("selfTests.expect 须选择非空files或errorCode")
        if "errorCode" in expect and expect["errorCode"] not in seen:
            raise ComputeError("selfTests.expect.errorCode 须在错误码表中声明")
        if "files" in expect:
            if not isinstance(expect["files"], dict):
                raise ComputeError("selfTests.expect.files 须为文件摘要对象")
            declared = {item["file"] for item in result["outputs"]}
            for filename, summary in expect["files"].items():
                if filename not in declared:
                    raise ComputeError("selfTests 期望输出未在outputs声明：" + filename)
                object_keys(
                    summary,
                    {"rows", "columns", "sha256", "contains", "bands"},
                    (),
                    "selfTests.expect.files",
                )
                for key in ("rows", "bands"):
                    if key in summary and (
                        type(summary[key]) is not int or summary[key] < 0
                    ):
                        raise ComputeError("selfTests 摘要行数/波段数须为非负整数")
                if "columns" in summary and (
                    not isinstance(summary["columns"], list)
                    or any(not isinstance(column, str) for column in summary["columns"])
                ):
                    raise ComputeError("selfTests.columns 须为字段名列表")
                if "sha256" in summary and not re.fullmatch(
                    r"[a-f0-9]{64}", str(summary["sha256"])
                ):
                    raise ComputeError("selfTests.sha256 无效")
                if "contains" in summary:
                    text(summary["contains"], "selfTests.contains", 1000)
    result.update(
        errors=deepcopy(errors),
        resources=deepcopy(resources),
        selfTests=deepcopy(tests),
    )
