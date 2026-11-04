from types import SimpleNamespace

import pytest

from apps.agent.demo_decisions import _awaiting_multi_proposal

APPLY = {"identifier": "geology-multi-apply"}


def workflow(workflow_type="geology_generic", check=True, applied=False, approved=()):
    stages = [{"name": "check", **({"taskId": "c1"} if check else {})}]
    stages.append({"name": "apply", **({"taskId": "a1"} if applied else {})})
    plan = {
        "stages": stages,
        "modificationReview": {"approvedSuggestionIds": list(approved)},
    }
    return SimpleNamespace(workflow_type=workflow_type, plan=plan)


@pytest.mark.parametrize(
    "kwargs, stage, expected",
    [
        ({}, APPLY, True),
        ({"workflow_type": "geology_multi_element_reasoning"}, APPLY, True),
        ({"check": False}, APPLY, False),
        ({"applied": True}, APPLY, False),
        ({"approved": ["s1"]}, APPLY, False),
        ({"workflow_type": "geology_map_review"}, APPLY, False),
        ({}, {"identifier": "geology-multi-check"}, False),
    ],
)
def test_only_unapproved_apply_proposal_requires_suggestions(kwargs, stage, expected):
    assert _awaiting_multi_proposal(workflow(**kwargs), stage) is expected
