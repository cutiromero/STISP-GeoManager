import type {
  AgentComputeTaskList,
  AgentResourceList,
  AgentWorkflow,
  AgentWorkflowList,
  AgentWorkflowSummaryList,
} from "./generated/types.gen";
import {
  assertComputeTask,
  responseArray,
  responseField,
  responseObject,
  responseValues,
} from "./computeResponse";
import { ResponseFormatError } from "./responseDiagnostics";

const WORKFLOW_STATUSES = new Set([
  "queued",
  "running",
  "waiting_compute",
  "waiting_approval",
  "paused",
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
]);

function summary(value: unknown, path: string) {
  const workflow = responseObject(value, path);
  for (const key of [
    "id",
    "workflowType",
    "goal",
    "status",
    "detail",
    "currentStep",
    "createdAt",
    "updatedAt",
  ])
    responseField(workflow, key, "string", path);
  responseField(workflow, "projectId", "number", path);
  if (!WORKFLOW_STATUSES.has(workflow.status as string))
    throw new ResponseFormatError(`${path}.status: invalid status`);
  return workflow;
}

export function assertWorkflow(
  value: unknown,
  path = "workflow",
): asserts value is AgentWorkflow {
  const workflow = summary(value, path);
  const plan = responseObject(workflow.plan, `${path}.plan`);
  responseObject(workflow.parameters, `${path}.parameters`);
  responseField(workflow, "planHash", "string", path);
  for (const key of ["resourceIds", "resultIds", "resultResourceIds"])
    responseValues(workflow[key], "number", `${path}.${key}`);
  for (const key of ["inputs", "parameters", "knowledgeSelection"])
    if (plan[key] !== undefined)
      responseObject(plan[key], `${path}.plan.${key}`);
  responseArray(workflow.evidence, `${path}.evidence`).forEach((entry, index) =>
    responseObject(entry, `${path}.evidence[${index}]`),
  );
  responseArray(workflow.steps, `${path}.steps`).forEach((entry, index) => {
    const stepPath = `${path}.steps[${index}]`;
    const step = responseObject(entry, stepPath);
    for (const key of ["id", "sequence"])
      responseField(step, key, "number", stepPath);
    for (const key of ["kind", "status", "message", "computeTaskId"])
      responseField(step, key, "string", stepPath);
    for (const key of ["action", "inputRefs", "outputRefs", "metrics"])
      responseObject(step[key], `${stepPath}.${key}`);
    if (step.decision != null) {
      const decisionPath = `${stepPath}.decision`;
      const decision = responseObject(step.decision, decisionPath);
      for (const key of [
        "problem",
        "judgement",
        "nextAction",
        "algorithmReason",
        "modelMode",
        "modelName",
      ])
        responseField(decision, key, "string", decisionPath);
      for (const key of ["findings", "uncertainties"])
        responseValues(decision[key], "string", `${decisionPath}.${key}`);
      responseArray(
        decision.evidenceRefs,
        `${decisionPath}.evidenceRefs`,
      ).forEach((ref, index) => {
        const refPath = `${decisionPath}.evidenceRefs[${index}]`;
        const evidence = responseObject(ref, refPath);
        for (const key of ["id", "kind", "title"])
          responseField(evidence, key, "string", refPath);
      });
    }
  });
  if (workflow.modificationReview != null) {
    const reviewPath = `${path}.modificationReview`;
    const review = responseObject(workflow.modificationReview, reviewPath);
    responseField(review, "proposalHash", "string", reviewPath);
    responseValues(
      review.approvedSuggestionIds,
      "string",
      `${reviewPath}.approvedSuggestionIds`,
    );
    responseArray(review.suggestions, `${reviewPath}.suggestions`).forEach(
      (entry, index) => {
        const suggestionPath = `${reviewPath}.suggestions[${index}]`;
        const suggestion = responseObject(entry, suggestionPath);
        for (const key of [
          "id",
          "kind",
          "featureId",
          "title",
          "currentState",
          "suggestedState",
          "reason",
          "ruleId",
        ])
          responseField(suggestion, key, "string", suggestionPath);
        responseField(suggestion, "areaM2", "number", suggestionPath);
        for (const key of ["ruleConditions", "exceptions"])
          if (suggestion[key] !== undefined)
            responseValues(
              suggestion[key],
              "string",
              `${suggestionPath}.${key}`,
            );
        responseArray(
          suggestion.knowledgeRefs,
          `${suggestionPath}.knowledgeRefs`,
        ).forEach((ref, index) => {
          const refPath = `${suggestionPath}.knowledgeRefs[${index}]`;
          const knowledge = responseObject(ref, refPath);
          for (const key of ["id", "revision"])
            responseField(knowledge, key, "number", refPath);
          responseField(knowledge, "title", "string", refPath);
        });
      },
    );
  }
}

export function assertWorkflowList(
  value: unknown,
): asserts value is AgentWorkflowList {
  const data = responseObject(value, "workflows");
  responseArray(data.items, "workflows.items").forEach((entry, index) =>
    assertWorkflow(entry, `workflows.items[${index}]`),
  );
}

export function assertWorkflowSummaryList(
  value: unknown,
): asserts value is AgentWorkflowSummaryList {
  const data = responseObject(value, "workflows");
  for (const key of ["total", "offset", "limit"])
    responseField(data, key, "number", "workflows");
  responseField(data, "hasMore", "boolean", "workflows");
  responseArray(data.items, "workflows.items").forEach((entry, index) =>
    summary(entry, `workflows.items[${index}]`),
  );
}

export function assertAgentComputeTasks(
  value: unknown,
): asserts value is AgentComputeTaskList {
  const data = responseObject(value, "computeTasks");
  responseArray(data.items, "computeTasks.items").forEach((entry, index) => {
    const path = `computeTasks.items[${index}]`;
    const item = responseObject(entry, path);
    assertComputeTask(item.task, `${path}.task`);
    responseField(item, "autoImport", "boolean", path);
    for (const key of ["trackingStatus", "detail"])
      responseField(item, key, "string", path);
  });
}

export function assertAgentResources(
  value: unknown,
): asserts value is AgentResourceList {
  const data = responseObject(value, "resources");
  responseArray(data.items, "resources.items").forEach((entry, index) => {
    const path = `resources.items[${index}]`;
    const item = responseObject(entry, path);
    responseField(item, "id", "number", path);
    for (const key of ["name", "dataType", "description"])
      responseField(item, key, "string", path);
  });
}
