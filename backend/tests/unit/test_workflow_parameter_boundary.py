"""Orchestration state must not become scientific operator parameters."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.agent import geology_multi
from apps.compute.packages import ComputeError


def test_business_flow_metadata_is_separated_without_mutating_the_binding():
    binding={"flowId":7,"versionId":7,"runId":23}
    workflow=SimpleNamespace(plan={"inputs":{}},parameters={"working_epsg":32646,"segment":"all","_businessFlow":binding},project_tag_id=3)
    class StopAfterBoundary(Exception):
        pass
    with patch.object(geology_multi,"require_actor"),patch.object(geology_multi,"validate_inputs",side_effect=StopAfterBoundary) as validate:
        with pytest.raises(StopAfterBoundary):geology_multi.prepare(workflow,None,{})
    assert validate.call_args.args[3]=={"working_epsg":32646,"segment":"all"}
    assert workflow.parameters["_businessFlow"] is binding


def test_unknown_scientific_parameters_are_still_rejected():
    with pytest.raises(ComputeError,match="未声明参数"):
        geology_multi.validate_inputs(None,{},dict.fromkeys(geology_multi.ROLES,1),{"invented_option":1})
