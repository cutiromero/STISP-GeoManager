"""Validate confirmed fixed parameters without reading scientific files."""

from apps.compute.packages import ComputeError


class MissingFixedParameters(ComputeError):
    def __init__(self, parameters):
        failure = {
            "code": "NODE_PARAMETERS_MISSING",
            "remedy": "human_review",
            "parameters": [row["key"] for row in parameters],
        }
        super().__init__(
            "请先确认必填任务参数："
            + "、".join(row.get("label", row["key"]) for row in parameters)
            + "；固定参数须由用户在启动准备中选择，不能由智能体猜测。",
            failure=failure,
        )


def require_fixed_parameters(manifest, confirmed):
    effective = {
        row["key"]: confirmed.get(row["key"], row.get("default"))
        for row in manifest["parameters"]
    }
    # A port can explicitly declare that all four omitted bounds mean the
    # authorized input footprint. Resolve that footprint only in compute
    # preflight, after binding real inputs. Partial or explicit null bounds
    # still need correction here; a required time index never gets defaulted.
    windows = {
        tuple(raster.get("window", []))
        for port in manifest.get("inputs", [])
        if (raster := port.get("raster") or {}).get("defaultExtent") is True
    }
    inferred = set()
    if len(windows) == 1:
        keys = next(iter(windows))
        if (
            len(keys) == 4
            and len(set(keys)) == 4
            and all(key not in confirmed and effective.get(key) is None for key in keys)
        ):
            inferred = set(keys)
    missing = []
    fixed = []
    for row in manifest["parameters"]:
        if row["key"] in inferred or row.get("agent", {}).get("adjustable") is True:
            continue
        when = row.get("when")
        if when and effective.get(when["key"]) != when["equals"]:
            continue
        fixed.append({key: value for key, value in row.items() if key != "when"})
        if row.get("required", True) and effective[row["key"]] is None:
            missing.append(row)
    if missing:
        raise MissingFixedParameters(missing)
    from apps.compute.services import parameter_values

    parameter_values({"parameters": fixed}, {}, confirmed, check_inputs=False)
