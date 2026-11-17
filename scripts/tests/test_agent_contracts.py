import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "agent_contract_generator", ROOT / "scripts/generate_agent_contracts.py"
)
generator = importlib.util.module_from_spec(loader)
loader.loader.exec_module(generator)


def test_generated_contracts_are_current():
    source = yaml.safe_load(generator.SPEC.read_text())
    registered = generator.registrations(generator.REGISTRY.read_text())
    import json

    assert generator.generate(source, registered) == json.loads(
        generator.OUTPUT.read_text()
    )


@pytest.mark.parametrize(
    "change",
    ["unknown_operation", "extra_argument", "missing_tool", "unsafe_arguments"],
)
def test_contract_gate_rejects_drift(change):
    source = copy.deepcopy(yaml.safe_load(generator.SPEC.read_text()))
    registered = generator.registrations(generator.REGISTRY.read_text())
    tool = source["x-agent-tools"]["search_resources"]
    if change == "unknown_operation":
        tool["operationIds"] = ["doesNotExist"]
    elif change == "missing_tool":
        del source["x-agent-tools"]["search_resources"]
    else:
        schema = source["components"]["schemas"][
            tool["inputSchema"]["$ref"].split("/")[-1]
        ]
        if change == "extra_argument":
            schema["properties"]["ownerId"] = {"type": "integer"}
        else:
            schema["additionalProperties"] = True
    with pytest.raises(ValueError):
        generator.generate(source, registered)
