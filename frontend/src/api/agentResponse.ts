import type {
  AgentConversation,
  AgentConversationDetail,
  AgentConversationList,
  AgentRun,
  AgentRunPoll,
} from "./generated/types.gen";
import { ResponseFormatError } from "./responseDiagnostics";

function object(value: unknown, path: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ResponseFormatError(`${path}: expected object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new ResponseFormatError(`${path}: expected array`);
  }
  return value;
}

function field(
  record: Record<string, unknown>,
  key: string,
  type: "string" | "number" | "boolean",
  path: string,
) {
  if (
    typeof record[key] !== type ||
    (type === "number" && !Number.isFinite(record[key]))
  ) {
    throw new ResponseFormatError(`${path}.${key}: expected ${type}`);
  }
}

export function assertConversation(
  value: unknown,
  path = "conversation",
): asserts value is AgentConversation {
  const record = object(value, path);
  for (const key of ["id", "projectId"]) field(record, key, "number", path);
  for (const key of ["title", "createdAt", "updatedAt"])
    field(record, key, "string", path);
  field(record, "archived", "boolean", path);
  if (record.mode !== "chat" && record.mode !== "agent") {
    throw new ResponseFormatError(`${path}.mode: invalid mode`);
  }
}

const RUN_STATUSES = new Set([
  "queued",
  "running",
  "waiting_input",
  "waiting_review",
  "waiting_compute",
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
]);

export function assertAgentRun(
  value: unknown,
  path = "run",
): asserts value is AgentRun {
  const run = object(value, path);
  for (const key of ["id", "conversationId"]) field(run, key, "number", path);
  for (const key of [
    "model",
    "prompt",
    "answer",
    "detail",
    "createdAt",
    "updatedAt",
  ])
    field(run, key, "string", path);
  if (!RUN_STATUSES.has(run.status as string)) {
    throw new ResponseFormatError(`${path}.status: invalid status`);
  }
  if (run.answerPreview !== undefined) {
    field(run, "answerPreview", "string", path);
    if (Array.from(run.answerPreview as string).length > 24000)
      throw new ResponseFormatError(`${path}.answerPreview: too long`);
  }
  for (const key of ["evidence", "attachments"]) {
    array(run[key], `${path}.${key}`).forEach((item, index) => {
      const itemPath = `${path}.${key}[${index}]`;
      const entry = object(item, itemPath);
      field(entry, "id", "number", itemPath);
      for (const name of key === "evidence"
        ? ["name", "tool"]
        : ["fileName", "kind"])
        field(entry, name, "string", itemPath);
      if (key === "evidence") object(entry.result, `${itemPath}.result`);
    });
  }
  for (const key of [
    "algorithmVersionIds",
    "resourceIds",
    "resolvedKnowledgeDomains",
  ]) {
    if (run[key] != null) array(run[key], `${path}.${key}`);
  }
  if (run.knowledgeSelection != null) {
    const selection = object(
      run.knowledgeSelection,
      `${path}.knowledgeSelection`,
    );
    array(selection.domains, `${path}.knowledgeSelection.domains`);
  }
  if (run.interactionHistory !== undefined) {
    array(run.interactionHistory, `${path}.interactionHistory`).forEach(
      (item, index) =>
        interaction(item, `${path}.interactionHistory[${index}]`),
    );
  }
  if (run.interaction != null)
    interaction(run.interaction, `${path}.interaction`);
  for (const key of [
    "computeIntent",
    "researchIntent",
    "generationParameters",
  ]) {
    if (run[key] != null) object(run[key], `${path}.${key}`);
  }
}

function interaction(value: unknown, path: string) {
  const record = object(value, path);
  field(record, "questionId", "string", path);
  array(record.questions, `${path}.questions`).forEach((item, index) => {
    const question = object(item, `${path}.questions[${index}]`);
    field(question, "key", "string", `${path}.questions[${index}]`);
    field(question, "label", "string", `${path}.questions[${index}]`);
    if (question.options !== undefined) {
      array(question.options, `${path}.questions[${index}].options`).forEach(
        (option, optionIndex) => {
          const entry = object(
            option,
            `${path}.questions[${index}].options[${optionIndex}]`,
          );
          field(entry, "label", "string", path);
          field(entry, "value", "string", path);
        },
      );
    }
  });
}

export function assertConversationDetail(
  value: unknown,
): asserts value is AgentConversationDetail {
  const data = object(value, "response");
  const conversation = data.conversation;
  assertConversation(conversation);
  array(data.runs, "runs").forEach((run, index) => {
    assertAgentRun(run, `runs[${index}]`);
    if (run.conversationId !== conversation.id) {
      throw new ResponseFormatError(`runs[${index}].conversationId: mismatch`);
    }
  });
}

export function assertConversationList(
  value: unknown,
): asserts value is AgentConversationList {
  const data = object(value, "response");
  array(data.items, "items").forEach((item, index) =>
    assertConversation(item, `items[${index}]`),
  );
}

export function assertRunPoll(value: unknown): asserts value is AgentRunPoll {
  const data = object(value, "response");
  assertAgentRun(data.run);
  field(data, "cursor", "number", "response");
  array(data.events, "events").forEach((item, index) => {
    const event = object(item, `events[${index}]`);
    field(event, "id", "number", `events[${index}]`);
    field(event, "kind", "string", `events[${index}]`);
    field(event, "text", "string", `events[${index}]`);
  });
}
