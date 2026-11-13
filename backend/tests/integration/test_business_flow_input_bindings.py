"""Published input edges identify authorized roles or actual predecessor outputs."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.business_flows.catalog import register_flow
from apps.business_flows.definitions import normalize_definition
from apps.business_flows.builtins import geology_definition
from apps.compute.models import AlgorithmResource, AlgorithmVersion
from apps.projects.context import project_scope
from apps.projects.models import Project
from tests.integration.test_agent import setup_agent  # noqa: F401

# ruff: noqa: F811


def operator_node(identity, version, dependencies, bindings):
    return {
        "id": identity,
        "title": identity,
        "description": "按登记算子处理",
        "kind": "operator",
        "dependsOn": dependencies,
        "dataRoles": [],
        "algorithmVersionId": version,
        "instruction": "",
        "inputBindings": bindings,
        "review": {"ai": False, "human": False, "maxRevisions": 0},
    }


def definition(up=1, down=2):
    return {
        "schemaVersion": 1,
        "adapter": "research_flow",
        "inputRequirements": [
            {
                "key": "source",
                "label": "原始资料",
                "description": "矢量资料",
                "dataTypes": ["vector"],
                "required": True,
                "requiredFields": [],
            }
        ],
        "nodes": [
            operator_node("upstream", up, [], {"source": {"role": "source"}}),
            {
                "id": "interpret",
                "title": "解释中间结果",
                "description": "理解实际输出",
                "kind": "agent",
                "dependsOn": ["upstream"],
                "dataRoles": [],
                "instruction": "基于前序输出解释",
                "review": {"ai": False, "human": False, "maxRevisions": 0},
            },
            operator_node(
                "downstream",
                down,
                ["interpret"],
                {"source": {"nodeId": "upstream", "outputKey": "clean"}},
            ),
        ],
        "outputRequirements": ["组合处理结果"],
    }


def test_binding_accepts_initial_role_and_transitive_operator_ancestor():
    normalized = normalize_definition(definition())
    assert normalized["nodes"][0]["inputBindings"]["source"] == {"role": "source"}
    assert normalized["nodes"][2]["inputBindings"]["source"] == {
        "nodeId": "upstream",
        "outputKey": "clean",
    }
    # Dependency order, rather than incidental array order, defines the predecessor.
    unordered = definition()
    unordered["nodes"].reverse()
    assert normalize_definition(unordered)["nodes"][0]["id"] == "downstream"


@pytest.mark.parametrize(
    "source",
    [
        {"role": "missing"},
        {"role": []},
        {"role": "source", "nodeId": "upstream", "outputKey": "clean"},
        {"nodeId": "downstream", "outputKey": "clean"},
        {"nodeId": "missing", "outputKey": "clean"},
        {"nodeId": "interpret", "outputKey": "clean"},
        {"nodeId": "upstream"},
        {"nodeId": [], "outputKey": "clean"},
        {"nodeId": "upstream", "outputKey": []},
        {"resourceId": 123},
        {"taskId": str(uuid4()), "outputKey": "clean"},
    ],
)
def test_binding_rejects_unknown_ambiguous_self_or_external_sources(source):
    spec = definition()
    spec["nodes"][2]["inputBindings"] = {"source": source}
    with pytest.raises(ValidationError):
        normalize_definition(spec)


def test_binding_rejects_future_or_nonancestor_outputs():
    spec = definition()
    spec["nodes"][0]["inputBindings"] = {
        "source": {"nodeId": "downstream", "outputKey": "clean"}
    }
    with pytest.raises(ValidationError):
        normalize_definition(spec)
    spec = definition()
    spec["nodes"][2]["dependsOn"] = []
    with pytest.raises(ValidationError):
        normalize_definition(spec)


def test_only_generic_operator_nodes_may_declare_input_edges():
    spec = definition()
    spec["nodes"][1]["inputBindings"] = {"source": {"role": "source"}}
    with pytest.raises(ValidationError):
        normalize_definition(spec)
    spec = geology_definition()
    spec["nodes"][1]["inputBindings"] = {}
    with pytest.raises(ValidationError):
        normalize_definition(spec)
    spec = definition()
    spec["nodes"][0]["inputBindings"] = {
        f"input-{index}": {"role": "source"} for index in range(31)
    }
    with pytest.raises(ValidationError):
        normalize_definition(spec)


@pytest.fixture
def versions(setup_agent):
    env = setup_agent

    def create(
        *,
        input_kind="vector",
        output_kind="vector",
        status="published",
        agent=True,
        project_id=None,
    ):
        with project_scope(env["scope"]):
            if project_id is None:
                algorithm = AlgorithmResource.objects.create(
                    identifier="bound-" + uuid4().hex[:12],
                    name="已登记处理算子",
                    created_by=env["admin"],
                    enabled=True,
                )
            else:
                # Explicit other-project fixtures are not created under the selected scope.
                algorithm = None
        if algorithm is None:
            algorithm = AlgorithmResource._base_manager.create(
                project_tag_id=project_id,
                identifier="bound-" + uuid4().hex[:12],
                name="其他项目算子",
                created_by=env["admin"],
                enabled=True,
            )
        return AlgorithmVersion.objects.create(
            algorithm=algorithm,
            version="1.0.0",
            checksum="a" * 64,
            package_path="unread-operator.zip",
            status=status,
            manifest={
                "inputs": [{"key": "source", "kind": input_kind, "required": True}],
                "outputs": [
                    {
                        "key": "clean",
                        "kind": output_kind,
                        "label": "处理结果",
                        "required": True,
                    }
                ],
                "parameters": [],
                "agent": {"enabled": agent},
            },
        )

    return {**env, "version": create}


def publish(env, spec):
    with project_scope(env["scope"]):
        return register_flow(
            env["admin"],
            {
                "code": "chain-" + uuid4().hex[:12],
                "name": "链式处理",
                "definition": spec,
            },
        )


def test_publication_checks_real_manifest_input_and_upstream_output(versions):
    env = versions
    up = env["version"]()
    down = env["version"]()
    flow, version = publish(env, definition(up.pk, down.pk))
    assert flow.current_version_id == version.pk
    assert (
        version.definition["nodes"][2]["inputBindings"]["source"]["outputKey"]
        == "clean"
    )
    for field, binding in [
        ("unknown", {"nodeId": "upstream", "outputKey": "clean"}),
        ("source", {"nodeId": "upstream", "outputKey": "missing"}),
    ]:
        spec = definition(up.pk, down.pk)
        spec["nodes"][2]["inputBindings"] = {field: binding}
        with pytest.raises(ValidationError):
            publish(env, spec)


@pytest.mark.parametrize(
    "output_kind,input_kind",
    [("raster", "vector"), ("archive", "vector"), ("image", "table")],
)
def test_publication_rejects_incompatible_or_archive_outputs(
    versions, output_kind, input_kind
):
    env = versions
    up = env["version"](output_kind=output_kind)
    down = env["version"](input_kind=input_kind)
    with pytest.raises(ValidationError):
        publish(env, definition(up.pk, down.pk))


def test_role_binding_must_be_compatible_with_target_manifest(versions):
    env = versions
    up = env["version"](input_kind="raster")
    down = env["version"]()
    with pytest.raises(ValidationError):
        publish(env, definition(up.pk, down.pk))


@pytest.mark.parametrize("status,agent", [("draft", True), ("published", False)])
def test_binding_never_uses_unpublished_or_disallowed_algorithm(
    versions, status, agent
):
    env = versions
    up = env["version"](status=status, agent=agent)
    down = env["version"]()
    with pytest.raises(ValidationError):
        publish(env, definition(up.pk, down.pk))


def test_binding_cannot_reference_another_private_project_algorithm(versions):
    env = versions
    other = Project.objects.create(code="other-binding-project", name="其他项目")
    up = env["version"](project_id=other.pk)
    down = env["version"]()
    with pytest.raises(ValidationError):
        publish(env, definition(up.pk, down.pk))


@pytest.mark.efficiency
def test_publication_reads_binding_metadata_in_a_batch_without_scanning_files(versions):
    env = versions
    up = env["version"]()
    down = env["version"]()
    with patch(
        "apps.compute.packages.checksum",
        side_effect=AssertionError("publication must not scan operator files"),
    ):
        with CaptureQueriesContext(connection) as queries:
            publish(env, definition(up.pk, down.pk))
    reads = [row for row in queries if 'FROM "compute_algorithmversion"' in row["sql"]]
    assert len(reads) == 1


def test_default_parameters_are_checked_against_the_loaded_manifest(versions):
    env = versions
    up = env["version"]()
    down = env["version"]()
    spec = definition(up.pk, down.pk)
    spec["nodes"][0]["parameters"] = {"not_declared": 1}
    with (
        CaptureQueriesContext(connection) as queries,
        pytest.raises(ValidationError, match="默认参数"),
    ):
        publish(env, spec)
    assert sum('FROM "compute_algorithmversion"' in row["sql"] for row in queries) == 1


def test_declared_default_parameters_publish_without_reading_source_files(versions):
    env = versions
    up = env["version"]()
    down = env["version"]()
    up.manifest["parameters"] = [
        {
            "key": "threshold",
            "label": "阈值",
            "type": "number",
            "required": False,
            "default": 0,
        }
    ]
    up.save(update_fields=["manifest"])
    spec = definition(up.pk, down.pk)
    spec["nodes"][0]["parameters"] = {"threshold": 1.5}
    with patch(
        "apps.compute.packages.checksum",
        side_effect=AssertionError("publication must not read package files"),
    ):
        _flow, version = publish(env, spec)
    assert version.definition["nodes"][0]["parameters"] == {"threshold": 1.5}


@pytest.mark.parametrize("value", [True, "0.5", -1, 2])
def test_publication_rejects_invalid_default_value_before_execution(versions, value):
    env = versions
    up, down = env["version"](), env["version"]()
    up.manifest["parameters"] = [
        {
            "key": "threshold",
            "label": "阈值",
            "type": "number",
            "required": False,
            "default": 0.5,
            "min": 0,
            "max": 1,
        }
    ]
    up.save(update_fields=["manifest"])
    spec = definition(up.pk, down.pk)
    spec["nodes"][0]["parameters"] = {"threshold": value}
    with pytest.raises(ValidationError, match="默认参数"):
        publish(env, spec)
