"""The public case uses authorized inputs and preserves historical workflow access."""

# ruff: noqa: F811
import copy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.agent.demo_workflow import prepare_demo
from apps.agent.models import AgentRuntime, AgentWorkflow
from apps.agent.research_intents import process
from apps.agent.research_parser import plausible, validate
from apps.agent.research_presets import REVIEW_MARKERS, discover, list_demos, PROMPTS
from apps.catalog.models import DataResource
from apps.compute.models import ComputeTask
from apps.compute.packages import ComputeError
from tests.integration.test_chat_research_intent import run
from tests.integration.test_compute import setup_compute  # noqa: F401
from tests.integration.test_demo_workflow import demo  # noqa: F401
from tests.integration.test_geology_map_review_workflow import review_case  # noqa: F401
from tests.integration.test_research_presets import mark

pytestmark = pytest.mark.django_db


def mark_review(env):
    inputs = env["workflow"].plan["inputs"]
    for role, (field, value) in REVIEW_MARKERS.items():
        resource = DataResource.objects.get(pk=inputs[role])
        setattr(resource, field, value)
        resource.source = "geology-review-material:input-v1"
        resource.name = {
            "initial_map": "待检查地质图",
            "coverage": "制图覆盖范围",
            "rules": "专家知识适用规则",
        }[role]
        resource.description = "演示案例：检查完整覆盖和地层时代属性。"
        resource.save()
    return inputs


def scene(env, run=None):
    return next(
        item
        for item in discover(env["owner"], env["policy"], run)["scenarios"]
        if item["scenario"] == "geology_map_review"
    )


def include_native_limit(env):
    for identifier in ("geology-map-check", "geology-map-correct"):
        version = env["versions"][identifier]
        version.manifest["parameters"] = [
            {"key": "max_changes", "type": "integer", "default": 2}
        ]
        version.save()


def parser_value(inputs):
    return {
        "action": "start",
        "scenario": "geology_map_review",
        "goal": "检查待检查地质图并提出建议，批准后修正",
        "message": "将查阅专家知识、检查地图并提交建议供您批准",
        "inputs": dict(inputs),
        "parameters": {},
        "questions": [],
    }


def test_new_case_discovery_keeps_exact_roles_and_audience_language(review_case):
    env = review_case
    inputs = mark_review(env)
    include_native_limit(env)
    result = scene(env)
    assert result["available"] and result["preferredInputs"] == inputs
    assert set(result["inputs"]) == {"initial_map", "coverage", "rules"}
    assert {item["identifier"] for item in result["algorithms"]} == {
        "geology-map-check",
        "geology-map-correct",
    }
    visible = str(result) + PROMPTS["geology_map_review"]
    for forbidden in ("师弟", "精修图", "人工设错", "参考真值"):
        assert forbidden not in visible
    assert "演示案例" in result["sourceNote"]
    assert "批准" in PROMPTS["geology_map_review"]
    assert result["defaults"]["max_changes"] == 5
    assert (
        next(spec for spec in result["parameterSpecs"] if spec["key"] == "max_changes")[
            "default"
        ]
        == 5
    )
    assert {
        item["scenario"] for item in discover(env["owner"], env["policy"])["scenarios"]
    } == {
        "ecology_investigation",
        "geology_correction",
        "geology_age_correction",
        "geology_map_review",
        "geology_multi_element_reasoning",
    }


def test_expanded_preset_never_mixes_old_coverage_or_overrides_custom_limit(
    review_case,
):
    env = review_case
    inputs = mark_review(env)
    include_native_limit(env)
    coverage = DataResource.objects.get(pk=inputs["coverage"])
    coverage.code = "geology-review-coverage"
    coverage.save()
    automatic = scene(env)
    assert not automatic["available"]
    assert "coverage" not in automatic["preferredInputs"]
    assert not automatic["inputs"]["coverage"]
    assert automatic["defaults"]["max_changes"] == 2
    manual = SimpleNamespace(
        resource_ids=list(inputs.values()),
        data_selection_mode="manual",
        algorithm_version_ids=[],
        algorithm_selection_mode="auto",
    )
    result = scene(env, manual)
    assert result["available"]
    assert result["defaults"]["max_changes"] == 2
    assert coverage.id in {item["id"] for item in result["inputs"]["coverage"]}


def test_showcase_promotes_only_new_geology_and_ecology_with_budget_floor(review_case):
    env = review_case
    mark(env)
    mark_review(env)
    for name in ("worker", "workflow-worker"):
        AgentRuntime.objects.update_or_create(
            name=name, defaults={"heartbeat": timezone.now()}
        )
    with patch(
        "apps.agent.research_presets.visible_models",
        return_value=[{"status": "online"}],
    ):
        items = list_demos(env["owner"], env["policy"])["items"]
        assert {item["scenario"] for item in items} == {
            "ecology_investigation",
            "geology_map_review",
        }
        case = next(item for item in items if item["scenario"] == "geology_map_review")
        assert case["sampleNature"] == "demonstration_case" and case["available"]
        for maximum, available in ((4, False), (5, True), (8, True)):
            items = list_demos(
                env["owner"], {**env["policy"], "maxIterations": maximum}
            )["items"]
            assert (
                next(
                    item for item in items if item["scenario"] == "geology_map_review"
                )["available"]
                is available
            )
    env["versions"]["geology-map-correct"].status = "trial_passed"
    env["versions"]["geology-map-correct"].save()
    assert not scene(env)["available"]


@pytest.mark.parametrize(
    "prefix",
    [
        "geology-case-reference-20261012:",
        "geology-review-reference:",
        "geology-review-acceptance:",
    ],
)
def test_internal_reference_never_enters_manual_catalog_or_runtime(review_case, prefix):
    env = review_case
    inputs = mark_review(env)
    resource = DataResource.objects.get(pk=inputs["initial_map"])
    resource.source = prefix + "isolated-validation"
    resource.save()
    manual = SimpleNamespace(
        resource_ids=list(inputs.values()),
        data_selection_mode="manual",
        algorithm_version_ids=[],
        algorithm_selection_mode="auto",
    )
    assert resource.id not in {
        item["id"] for rows in scene(env, manual)["inputs"].values() for item in rows
    }
    with pytest.raises(ComputeError, match="独立验收"):
        prepare_demo(env["workflow"], env["owner"], env["policy"])


def test_manual_resource_and_algorithm_selections_remain_ceilings(review_case):
    env = review_case
    inputs = mark_review(env)
    manual = SimpleNamespace(
        resource_ids=[inputs["initial_map"]],
        data_selection_mode="manual",
        algorithm_version_ids=[env["versions"]["geology-map-check"].id],
        algorithm_selection_mode="manual",
    )
    result = scene(env, manual)
    assert not result["available"]
    assert result["inputs"]["initial_map"]
    assert {item["id"] for rows in result["inputs"].values() for item in rows} == {
        inputs["initial_map"]
    }
    assert not result["inputs"]["rules"]
    assert [item["identifier"] for item in result["algorithms"]] == [
        "geology-map-check"
    ]
    hidden = DataResource.objects.get(pk=inputs["initial_map"])
    hidden.owner_only, hidden.maintainer = True, env["outsider"]
    hidden.save()
    assert not scene(env, manual)["inputs"]["initial_map"]


def test_natural_map_review_request_routes_and_parser_rejects_hidden_role_input(
    review_case,
):
    env = review_case
    inputs = mark_review(env)
    item = run(env, "请检查这张地质图")
    assert plausible(item, None)
    for prompt in ("请修正这张地质图", "请核对地层图的内部漏填"):
        assert plausible(SimpleNamespace(prompt=prompt, research_intent={}), None)
    catalog = discover(env["owner"], env["policy"])
    value = parser_value(inputs)
    assert (
        validate(copy.deepcopy(value), catalog, item)["scenario"]
        == "geology_map_review"
    )
    value["inputs"]["initial_map"] = env["inputs"]["early_image"]
    with pytest.raises(ValidationError, match="未授权或角色"):
        validate(value, catalog, item)


def test_natural_instruction_authorizes_checks_but_never_map_edit(review_case):
    env = review_case
    inputs = mark_review(env)
    # The fixture's earlier plan is only setup; this starts a new isolated chat.
    env["workflow"].delete()
    item = run(env, "请检查这张地质图，建议批准后再修正")
    item.knowledge_selection = {"mode": "auto", "domains": []}
    item.save()
    catalog = discover(env["owner"], env["policy"])
    with (
        patch("apps.agent.research_presets.discover", return_value=catalog),
        patch(
            "apps.agent.research_intents.interpret",
            return_value=(parser_value(inputs), {"modelMode": "mock"}),
        ),
    ):
        process(item, env["owner"], env["policy"], lambda: None, lambda *args: None)
    item.refresh_from_db()
    wf = AgentWorkflow.objects.get(pk=item.research_workflow_id)
    assert (
        wf.workflow_type == "geology_map_review"
        and wf.plan["chatExecution"]["initialPlanAuthorized"]
    )
    assert wf.plan["chatExecution"]["algorithmVersionIds"]
    prepare_demo(wf, env["owner"], env["policy"])
    wf.refresh_from_db()
    assert wf.status == "queued" and wf.execute_operators
    assert wf.plan["stages"][0]["identifier"] == "search_expert_knowledge"
    assert not wf.plan.get("modificationReview") and not ComputeTask.objects.exists()
