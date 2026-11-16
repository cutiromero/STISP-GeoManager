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
    missing = []
    fixed = []
    for row in manifest["parameters"]:
        if row.get("agent", {}).get("adjustable") is True:
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
