import type {
  AgentRun,
  AgentWorkflowModelActivity,
} from "./generated/types.gen";
import { ResponseFormatError } from "./responseDiagnostics";

const limit = 12000;
const invalid = (): never => {
  throw new ResponseFormatError(
    "workflowModelActivity",
    "工作流模型活动返回内容不完整",
  );
};

export function assertWorkflowActivity(
  value: unknown,
): asserts value is AgentWorkflowModelActivity {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  const v = value as Record<string, unknown>;
  if (
    typeof v.stage !== "string" ||
    typeof v.thinkingText !== "string" ||
    ![
      "requesting",
      "thinking",
      "responding",
      "validating",
      "complete",
      "failed",
    ].includes(String(v.status)) ||
    !["low", "medium", "xhigh"].includes(String(v.reasoningEffort)) ||
    typeof v.thinkingEnabled !== "boolean" ||
    typeof v.truncated !== "boolean" ||
    !Number.isSafeInteger(v.attempt) ||
    !Number.isSafeInteger(v.outputChars) ||
    (v.thinkingChars !== undefined && !Number.isSafeInteger(v.thinkingChars))
  )
    invalid();
}

export function workflowModelActivity(run: AgentRun) {
  const value = run.generationParameters?.workflowModelActivity;
  if (value === undefined) return undefined;
  assertWorkflowActivity(value);
  return value;
}

export function applyWorkflowModelEvent(run: AgentRun, raw: string): AgentRun {
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  const data = value as Record<string, unknown>;
  if (
    typeof data.workflowId !== "string" ||
    data.workflowId !== run.businessFlow?.id ||
    typeof data.sequence !== "number" ||
    !Number.isSafeInteger(data.sequence) ||
    typeof data.reset !== "boolean" ||
    typeof data.thinkingDelta !== "string" ||
    Array.from(data.thinkingDelta).length > limit ||
    !data.activity ||
    typeof data.activity !== "object" ||
    Array.isArray(data.activity)
  )
    invalid();
  const parameters = run.generationParameters ?? {};
  const previous = workflowModelActivity(run);
  const reset =
    data.reset || parameters.workflowModelActivitySequence !== data.sequence;
  const thinkingText = Array.from(
    (reset ? "" : (previous?.thinkingText ?? "")) + data.thinkingDelta,
  )
    .slice(-limit)
    .join("");
  const activity = {
    ...(data.activity as object),
    thinkingText,
  };
  assertWorkflowActivity(activity);
  return {
    ...run,
    generationParameters: {
      ...parameters,
      workflowModelActivity: activity,
      workflowModelActivitySequence: data.sequence as number,
    },
  };
}
