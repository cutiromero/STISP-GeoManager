"""Operator envelopes follow each real manifest's input names, not numeric keys."""
# ruff: noqa: F811 - pytest imports reusable fixtures by name.

import json

import pytest
from django.core.exceptions import ValidationError

from apps.agent.tools import execute
from apps.agent.worker import run_task
from apps.compute.models import ComputeTask
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_agent_compute_loop import env  # noqa: F401
from tests.integration.test_agent_interactions import mock_model


@pytest.fixture(params=[("source",), ("earlier", "later")])
def named_inputs(env, request):
    version = env["version"]
    template = version.manifest["inputs"][0]
    version.manifest = {
        **version.manifest,
        "inputs": [{**template, "key": key} for key in request.param],
        "parameters": [],
    }
    version.save(update_fields=["manifest"])
    return env, request.param


@pytest.mark.parametrize(
    "invalid",
    [
        "array",
        "numeric_key",
        "other_key",
        "string_value",
        "bool_value",
        "parameters_array",
    ],
)
def test_invalid_envelopes_report_actual_manifest_keys_without_submitting(
    named_inputs, invalid
):
    e, keys = named_inputs
    resource_id = e["resource"].id
    inputs, parameters = {key: resource_id for key in keys}, {}
    if invalid == "array":
        inputs = [resource_id]
    elif invalid == "numeric_key":
        inputs = {str(resource_id): resource_id}
    elif invalid == "other_key":
        inputs = {"image": resource_id}
    elif invalid == "string_value":
        inputs[keys[0]] = str(resource_id)
    elif invalid == "bool_value":
        inputs[keys[0]] = True
    else:
        parameters = []
    with pytest.raises(ValidationError) as caught:
        execute(
            e["run"],
            "execute_operator",
            {"versionId": e["version"].id, "inputs": inputs, "parameters": parameters},
        )
    detail = str(caught.value)
    assert json.dumps(list(keys), ensure_ascii=False) in detail
    assert "manifest.inputs[].key" in detail and "list_compute_algorithms" in detail
    assert "资源正整数ID" in detail and "参数名到值的对象" in detail
    assert not ComputeTask.objects.exists()
    e["run"].refresh_from_db()
    assert not e["run"].compute_intent


def test_protocol_correction_uses_named_inputs_and_creates_only_one_task(
    named_inputs, monkeypatch
):
    e, keys = named_inputs
    inputs = {key: e["resource"].id for key in keys}
    captured = []

    e["run"].status = "running"
    e["run"].prompt = "处理已选择的数据，完成后先不入库"
    e["run"].save(update_fields=["status", "prompt"])
    mock_model(
        monkeypatch,
        [
            {
                "action": "execute_operator",
                "arguments": {
                    "versionId": e["version"].id,
                    "inputs": list(inputs.values()),
                    "parameters": {},
                },
            },
            {
                "action": "execute_operator",
                "arguments": {
                    "versionId": e["version"].id,
                    "inputs": inputs,
                    "parameters": {},
                },
            },
        ],
        captured,
    )
    run_task(e["run"].id)
    e["run"].refresh_from_db()
    assert e["run"].status == "waiting_compute", e["run"].detail
    assert len(captured) == 2
    assert json.dumps(list(keys), ensure_ascii=False) in captured[1][-1]["content"]
    task = ComputeTask.objects.get()
    assert dict(task.input_records.values_list("key", "resource_id")) == inputs
    assert task.parameters == {}
    assert len(e["run"].evidence) == len(keys)
