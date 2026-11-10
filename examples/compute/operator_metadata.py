"""示例包构建时共用的第2版说明；不参与科学计算。"""

INPUT_ERROR = {
    "code": "INPUT_INVALID",
    "meaning": "实际输入、规则或参数未通过算子已有检查",
    "remedy": "replace_data",
    "precondition": "输入须满足清单语义及算子规则约束；人工批准必须绑定当前快照",
}
RESOURCE_HINT = {
    "duration": "minutes",
    "memory": "medium",
    "scaling": "时间随实际像元/要素与规则数量增加；栅格分块读取，复杂几何叠加可能增加峰值内存。small约小于512MiB，medium约512MiB至2GiB，large高于2GiB；均非资源保证。",
}


def field(role, description, types=None, *, required=True, legacy=None, name=None):
    value = {
        "role": role,
        "description": description,
        "types": types or ["string"],
        "required": required,
    }
    if legacy:
        value["legacyName"] = legacy
    if name:
        value["name"] = name
    return value


def enrich(manifest, operation, *, use_when=None, avoid_when=None):
    manifest["schemaVersion"] = 2
    manifest["capabilities"] = {
        "operations": [operation],
        "dataTypes": sorted({item["kind"] for item in manifest["inputs"]}),
        "summary": manifest["description"],
        "useWhen": use_when or "已获得真实授权来源，需要按声明生成派生数据。",
        "avoidWhen": avoid_when
        or "来源含义、类别名称或坐标系未知时，不猜测科学含义；先补齐来源和映射。",
    }
    for item in manifest["inputs"]:
        item.update(
            description=item["label"] + "；原始来源只读，输出为新派生数据。",
            fields=[],
            crs={"mode": "any"},
        )
    for parameter in manifest["parameters"]:
        parameter.setdefault(
            "help",
            parameter["label"] + "；按实际来源和任务目标设置，取值须满足声明范围。",
        )
        parameter["agent"] = {
            "adjustable": parameter["type"] not in {"field", "band"}
            and parameter["key"] not in {"working_epsg", "code", "target_contract"},
            "advice": "仅在来源证据和任务约束允许时按范围调整；不得为减少报错而放宽科学判据或人工批准。"
            if parameter["type"] not in {"field", "band"}
            else "根据实际字段或波段的语义证据绑定，不按名称猜测；优先使用字段映射。",
        }
        if parameter["type"] in {"field", "band"}:
            spec = next(
                item for item in manifest["inputs"] if item["key"] == parameter["input"]
            )
            spec["fields"].append(
                {
                    **field(
                        parameter["key"],
                        parameter["label"],
                        ["integer", "number"]
                        if parameter["type"] == "band"
                        else ["string", "integer", "number", "boolean", "datetime"],
                    ),
                    "parameter": parameter["key"],
                }
            )
    for item in manifest["outputs"]:
        item.update(
            description=item["label"]
            + "；语义与输入规则版本保持一致，不能作为独立地质真值。",
            fields=[],
            final=item["kind"] in {"vector", "raster"},
        )
    manifest["errors"] = [dict(INPUT_ERROR)]
    manifest["resources"] = dict(RESOURCE_HINT)
    return manifest


def adapter_manifest(manifest):
    enrich(
        manifest,
        "convert"
        if manifest["inputAdapter"]["targetKind"] != "table"
        else "statistics",
    )
    capability = manifest["inputAdapter"]
    output = manifest["outputs"][0]
    output["description"] = (
        capability["description"] + " 输出语义标识：" + capability["targetSemantics"]
    )
    output["final"] = False
    if capability["targetKind"] == "raster":
        output["fields"] = [
            field(
                "class_presence",
                "每波段一个真实名称类别；0无、1有、255无效；名称保存在band description",
                ["integer"],
            )
        ]
    else:
        output["fields"] = [
            field(name, description, types, name=name)
            for name, description, types in (
                ("band", "1起始波段号", ["integer"]),
                ("name", "原波段名称", ["string"]),
                ("count", "有效像元数量", ["integer"]),
                ("min", "有效像元最小值，保持原波段单位", ["number"]),
                ("max", "有效像元最大值，保持原波段单位", ["number"]),
                ("mean", "有效像元均值，保持原波段单位", ["number"]),
            )
        ]
    manifest["selfTests"] = [
        {
            "name": "小样例转换",
            "fixture": "selftest/smoke.json",
            "expect": {
                "files": {
                    output["file"]: {"bands": 1}
                    if output["kind"] == "raster"
                    else {"rows": 1, "columns": capability["outputFields"]}
                }
            },
        }
    ]
    return manifest
