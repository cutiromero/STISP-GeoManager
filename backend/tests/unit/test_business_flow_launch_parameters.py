from copy import deepcopy

import pytest

from apps.business_flows.launch_parameters import (
    MissingFixedParameters,
    require_fixed_parameters,
)
from apps.compute.packages import ComputeError


SPEC = {
    "parameters": [
        {
            "key": "product",
            "label": "观测产品",
            "type": "enum",
            "required": True,
            "default": "gwis_ba",
            "choices": ["gwis_ba", "fcci_ba"],
        },
        {
            "key": "time_index",
            "label": "原始时间索引",
            "type": "integer",
            "required": True,
            "min": 0,
            "agent": {"adjustable": False},
        },
    ]
}


def test_missing_confirmed_time_is_a_structured_human_requirement():
    with pytest.raises(MissingFixedParameters, match="原始时间索引") as caught:
        require_fixed_parameters(SPEC, {})
    assert caught.value.failure == {
        "code": "NODE_PARAMETERS_MISSING",
        "remedy": "human_review",
        "parameters": ["time_index"],
    }


@pytest.mark.parametrize("value", [0, 2000])
def test_zero_and_large_real_indices_are_not_treated_as_missing(value):
    require_fixed_parameters(SPEC, {"time_index": value})


@pytest.mark.parametrize("value", ["all", "0:966", -1, True])
def test_invalid_confirmed_indices_are_rejected_before_model_admission(value):
    with pytest.raises(ComputeError):
        require_fixed_parameters(SPEC, {"time_index": value})


def test_defaults_conditions_and_agent_adjustable_parameters_keep_their_semantics():
    manifest = deepcopy(SPEC)
    manifest["parameters"][1]["agent"]["adjustable"] = True
    require_fixed_parameters(manifest, {})
    manifest["parameters"][1]["agent"]["adjustable"] = False
    manifest["parameters"][1]["when"] = {"key": "product", "equals": "fcci_ba"}
    require_fixed_parameters(manifest, {})
    with pytest.raises(MissingFixedParameters):
        require_fixed_parameters(manifest, {"product": "fcci_ba"})
