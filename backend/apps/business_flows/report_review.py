"""Review final conclusions against the same complete report facts as execution."""

from apps.agent.demo_decisions import evidence_refs
from apps.agent.geology_multi_results import (
    model_knowledge,
    model_results,
    model_review,
)
from apps.agent.rule_dispositions import report_payload
from apps.compute.packages import ComputeError


def report_review_packet(workflow, decision, results, candidate_digest):
    if (
        workflow is None
        or not isinstance(candidate_digest, str)
        or len(candidate_digest) != 64
    ):
        raise ComputeError("最终审核缺少冻结的候选摘要")
    projected = model_results(results, stage_name="finish")
    quality = [
        {
            "outputId": item["outputId"],
            "taskId": item.get("taskId"),
            "checksum": item["checksum"],
            "qualityCheck": item["metadata"]["qualityCheck"],
        }
        for item in projected
        if isinstance(item.get("metadata", {}).get("qualityCheck"), dict)
    ]
    context = report_payload(
        {
            "actualResults": projected,
            "knowledge": [],
            "modificationReview": model_review(workflow),
            "availableEvidence": evidence_refs(workflow, [], results),
        },
        workflow,
    )
    context["knowledge"] = model_knowledge(context["knowledge"])
    context["reportReferences"] = context.pop("availableEvidence")
    return {
        "decision": decision,
        **context,
        "qualityEvidence": quality,
        "candidateDigest": candidate_digest,
    }
