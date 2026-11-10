"""复用计算中心真实候选元信息，生成可供输入适配器消费的语义差距。"""

from copy import deepcopy

from .packages import ComputeError


def expand_bindings(manifest, bindings):
    if manifest.get("schemaVersion", 1) != 2:
        return dict(bindings), {}, manifest["inputs"]
    flat, collections, specs = {}, {}, []
    for spec in manifest["inputs"]:
        key = spec["key"]
        if "repeat" not in spec:
            if key in bindings:
                flat[key] = bindings[key]
            specs.append(spec)
            continue
        values = bindings.get(key, [])
        repeat = spec["repeat"]
        if (
            not isinstance(values, list)
            or not repeat["min"] <= len(values) <= repeat["max"]
        ):
            raise ComputeError(
                f"{key} 集合数量须为{repeat['min']}至{repeat['max']}",
                gaps=[gap("INPUT_COUNT", key, "replace_data", expected=repeat)],
            )
        labels, entries = set(), []
        for index, item in enumerate(values, 1):
            if (
                not isinstance(item, dict)
                or set(item) - {"resourceId", "label"}
                or type(item.get("resourceId")) is not int
            ):
                raise ComputeError(key + " 集合成员须包含resourceId及可选label")
            label = item.get("label", "")
            if (
                not isinstance(label, str)
                or len(label) > 160
                or (repeat["labelRequired"] and not label.strip())
                or label
                and label in labels
            ):
                raise ComputeError(key + " 集合标签须为唯一的1至160字文字")
            labels.add(label)
            actual = f"{key}__{index}"
            if actual in {item["key"] for item in manifest["inputs"]}:
                raise ComputeError("集合展开键与清单输入冲突：" + actual)
            flat[actual] = item["resourceId"]
            specs.append({**spec, "key": actual, "sourceKey": key})
            entries.append({"key": actual, "label": label})
        collections[key] = entries
    if len(flat) > 128:
        raise ComputeError("单次任务最多接受128份实际输入")
    return flat, collections, specs


def gap(code, key, remedy, *, role="", field="", expected=None, actual=None):
    return {
        "code": code,
        "input": key,
        "role": role,
        "field": field,
        "expected": expected,
        "actual": actual,
        "remedy": remedy,
    }


def semantic_preflight(manifest, metadata, mappings, parameters, *, specs=None):
    """返回规范化映射及参数；不执行转换，不推断未知单位。"""
    if not isinstance(mappings, dict) or set(mappings) - set(metadata):
        raise ComputeError("fieldMappings 只能引用已绑定的实际输入键")
    result, normalized, gaps = {}, deepcopy(parameters), []
    specs = specs if specs is not None else manifest["inputs"]
    for spec in specs:
        key = spec["key"]
        if key not in metadata:
            continue
        info = metadata[key]
        selected = mappings.get(key, {})
        roles = {item["role"]: item for item in spec.get("fields", [])}
        if not isinstance(selected, dict) or set(selected) - set(roles):
            raise ComputeError(key + " 字段映射包含未声明的语义角色")
        bound = {}
        for role, requirement in roles.items():
            parameter = requirement.get("parameter")
            value = selected.get(role)
            if value is None and requirement.get("legacyName") in info.get(
                "fields", []
            ):
                value = requirement["legacyName"]
            if value is None and parameter:
                parameter_spec = next(
                    item for item in manifest["parameters"] if item["key"] == parameter
                )
                value = parameters.get(parameter, parameter_spec.get("default"))
            if value is None:
                if requirement["required"]:
                    gaps.append(
                        gap(
                            "MISSING_ROLE",
                            key,
                            "complete_mapping",
                            role=role,
                            expected=requirement,
                        )
                    )
                continue
            is_band = info["kind"] == "raster"
            exists = (
                type(value) is int and 1 <= value <= info["bands"]
                if is_band
                else isinstance(value, str) and value in info["fields"]
            )
            if not exists:
                gaps.append(
                    gap(
                        "MISSING_FIELD",
                        key,
                        "complete_mapping",
                        role=role,
                        field=str(value),
                        expected="实际字段名或1起始波段号",
                    )
                )
                continue
            bound[role] = value
            if parameter:
                if parameter in normalized and normalized[parameter] != value:
                    raise ComputeError(f"{key}.{role} 映射与参数{parameter}冲突")
                normalized[parameter] = value
            actual_type = info.get("fieldTypes", {}).get(str(value))
            expected_types = requirement["types"]
            if (
                actual_type is None
                or actual_type not in expected_types
                and not (actual_type == "integer" and "number" in expected_types)
            ):
                gaps.append(
                    gap(
                        "FIELD_TYPE" if actual_type else "UNKNOWN_FIELD_TYPE",
                        key,
                        "convert_input",
                        role=role,
                        field=str(value),
                        expected=expected_types,
                        actual=actual_type,
                    )
                )
            if "unit" in requirement:
                actual_unit = info.get("fieldUnits", {}).get(str(value))
                if actual_unit != requirement["unit"]:
                    gaps.append(
                        gap(
                            "FIELD_UNIT" if actual_unit else "UNKNOWN_FIELD_UNIT",
                            key,
                            "convert_input" if actual_unit else "human_review",
                            role=role,
                            field=str(value),
                            expected=requirement["unit"],
                            actual=actual_unit,
                        )
                    )
        result[key] = bound
        aliases = {
            bound[field["role"]]: field["legacyName"]
            for field in roles.values()
            if field.get("legacyName")
            and field["role"] in bound
            and bound[field["role"]] != field["legacyName"]
        }
        if any(
            target in info.get("fields", []) and target not in aliases
            for target in aliases.values()
        ):
            gaps.append(
                gap(
                    "FIELD_ALIAS_CONFLICT",
                    key,
                    "convert_input",
                    expected="内部规范列名无冲突",
                    actual=aliases,
                )
            )
        crs_spec = spec.get("crs", {"mode": "any"})
        mode = crs_spec["mode"]
        if mode != "any":
            from pyproj import CRS

            try:
                actual = CRS.from_user_input(info.get("crs"))
            except (ValueError, TypeError):
                actual = None
            valid = (
                actual is not None and actual.is_projected
                if mode == "projected"
                else False
            )
            if mode == "same_as" and actual is not None:
                reference = metadata.get(crs_spec["input"])
                try:
                    valid = bool(
                        reference
                        and actual.equals(CRS.from_user_input(reference["crs"]))
                    )
                except (ValueError, TypeError):
                    valid = False
            if not valid:
                gaps.append(
                    gap(
                        "CRS_MISMATCH",
                        key,
                        "convert_input",
                        expected=crs_spec,
                        actual=info.get("crs"),
                    )
                )
        if "spatial" in spec:
            from pyproj import CRS, Transformer
            from shapely.geometry import box
            from shapely.ops import transform

            relation = spec["spatial"]
            reference = metadata.get(relation["input"], {})
            valid = False
            try:
                current = box(*info["bounds"])
                target = box(*reference["bounds"])
                transformer = Transformer.from_crs(
                    CRS(info["crs"]), CRS(reference["crs"]), always_xy=True
                )
                current = transform(transformer.transform, current)
                valid = (
                    current.intersects(target)
                    if relation["relation"] == "intersects"
                    else target.covers(current)
                )
            except (ValueError, TypeError, KeyError):
                pass
            if not valid:
                gaps.append(
                    gap(
                        "SPATIAL_RELATION",
                        key,
                        "replace_data",
                        expected=relation,
                        actual=info.get("bounds"),
                    )
                )
    if gaps:
        raise ComputeError("输入语义预检未通过，请按gaps补齐映射或转换数据", gaps=gaps)
    return result, normalized
