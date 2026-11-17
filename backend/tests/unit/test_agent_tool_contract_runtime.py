import math

import pytest
from django.db import OperationalError

from apps.agent.tool_contract_runtime import (
    ToolContractError,
    failure,
    validate_arguments,
)


@pytest.mark.parametrize(
    "arguments,field",
    [
        ({"limit": True}, "$.limit"),
        ({"offset": -1}, "$.offset"),
        ({"limit": 0}, "$.limit"),
        ({"category": "private_all"}, "$.category"),
        ({"ownerId": 2}, "$.ownerId"),
    ],
)
def test_contract_rejects_typed_bounds_and_unregistered_scope(arguments, field):
    with pytest.raises(ToolContractError) as caught:
        validate_arguments("search_resources", arguments)
    problem = failure(caught.value)
    assert problem["code"] == "INVALID_TOOL_ARGUMENTS" and not problem["retryable"]
    assert field in {item["field"] for item in problem["fieldErrors"]}


def test_contract_keeps_existing_defaults_and_storage_id_types():
    validate_arguments("search_resources", {"limit": 5000})
    validate_arguments("summarize_data", {"resourceId": 1})
    validate_arguments("aggregate_data", {"resourceId": 1, "groupBy": "region"})
    validate_arguments("compare_summaries", {"evidenceIds": [1, 2]})
    validate_arguments("read_knowledge_document", {"documentId": 7})


@pytest.mark.parametrize(
    "arguments",
    [
        {"page": "https://bad.example/"},
        {"page": "map", "ownerId": 1},
    ],
)
def test_links_are_fixed_platform_destinations(arguments):
    with pytest.raises(ToolContractError):
        validate_arguments("get_platform_link", arguments)


def test_nonfinite_oversized_and_deep_json_are_rejected():
    deep = {}
    for _ in range(24):
        deep = {"item": deep}
    for facts in ({"value": math.nan}, {"value": "x" * 131072}, deep):
        with pytest.raises(ToolContractError):
            validate_arguments("check_knowledge_constraints", {"facts": facts})


def test_database_structure_errors_are_not_retryable_busy_errors():
    assert failure(OperationalError("database is locked"))["retryable"]
    problem = failure(OperationalError("no such column: private_schema"))
    assert problem["code"] == "DATABASE_SCHEMA_ERROR" and not problem["retryable"]
    assert "private_schema" not in str(problem)


def test_unexpected_failure_does_not_expose_parameters_or_paths():
    problem = failure(RuntimeError("secret-token /root/private/input.tif"))
    assert problem["code"] == "TOOL_EXECUTION_FAILED"
    assert "secret-token" not in str(problem) and "/root" not in str(problem)


def test_business_errors_are_classified_before_their_value_error_base():
    from apps.compute.packages import ComputeError
    from apps.agent.tool_contract_runtime import failure

    assert isinstance(ComputeError("conflict", 409), ValueError)
    assert failure(ComputeError("conflict", 409))["code"] == "REVISION_CONFLICT"
    assert failure(ComputeError("denied", 403))["code"] == "PERMISSION_DENIED"
    busy = failure(ComputeError("busy", 503))
    assert busy["code"] == "SERVICE_BUSY" and busy["retryable"] is True
