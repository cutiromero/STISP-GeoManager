import type {
  AgentEvent,
  AgentRun,
  AgentRunPoll,
  AgentStreamProgress,
} from "./generated/types.gen";
import { assertRunPoll } from "./agentResponse";
import { ApiError } from "./client";
import { ResponseFormatError } from "./responseDiagnostics";

export const MAX_ANSWER_PREVIEW = 1048576;
const active = (run: AgentRun) =>
  ["queued", "running", "waiting_compute"].includes(run.status);

function progress(value: unknown): asserts value is AgentStreamProgress {
  if (!value || typeof value !== "object")
    throw new ResponseFormatError("实时事件不是对象");
  const data = value as AgentStreamProgress;
  if (
    ![data.runId, data.conversationId, data.cursor, data.fromCursor].every(
      Number.isSafeInteger,
    ) ||
    data.fromCursor < 0 ||
    data.cursor < data.fromCursor ||
    !Array.isArray(data.events) ||
    data.events.length > 100
  )
    throw new ResponseFormatError("实时事件游标无效");
  let cursor = data.fromCursor;
  for (const event of data.events) {
    if (
      !Number.isSafeInteger(event.id) ||
      event.id <= cursor ||
      event.id > data.cursor ||
      typeof event.kind !== "string" ||
      typeof event.text !== "string"
    )
      throw new ResponseFormatError("实时事件顺序无效");
    cursor = event.id;
  }
  if (cursor !== data.cursor)
    throw new ResponseFormatError("实时事件游标不完整");
}

export function applyAgentEvents(
  run: AgentRun,
  events: AgentEvent[],
): AgentRun {
  let next = { ...run };
  for (const event of events) {
    if (event.kind === "thinking")
      next.thinkingText = (next.thinkingText ?? "") + event.text;
    else if (event.kind === "answer_preview") next.answerPreview = event.text;
    else if (event.kind === "answer_delta")
      next.answerPreview = (next.answerPreview ?? "") + event.text;
    else if (event.kind === "text")
      next = { ...next, answer: event.text, answerPreview: "" };
    else if (event.kind === "parameters") {
      const parameters: unknown = JSON.parse(event.text);
      if (
        parameters &&
        typeof parameters === "object" &&
        !Array.isArray(parameters)
      )
        next.generationParameters = parameters;
    }
  }
  const text = next.answerPreview ?? "";
  if (
    text.length > MAX_ANSWER_PREVIEW * 2 ||
    (text.length > MAX_ANSWER_PREVIEW &&
      Array.from(text).length > MAX_ANSWER_PREVIEW)
  )
    throw new ResponseFormatError("正文超过实时展示上限");
  return next;
}

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    signal.throwIfAborted();
    const cancel = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve();
    }, ms);
    signal.addEventListener("abort", cancel, { once: true });
  });
}

export async function watchAgentRun(
  initial: AgentRun,
  api: {
    poll: (
      id: number,
      after?: number,
      signal?: AbortSignal,
    ) => Promise<AgentRunPoll>;
    stream?: (
      id: number,
      callback: (kind: string, data: unknown) => void,
      signal?: AbortSignal,
    ) => Promise<void>;
  },
  signal: AbortSignal,
  onUpdate: (value: AgentRunPoll) => void,
  onFailure: (error: unknown) => void,
) {
  let run = initial,
    cursor = 0,
    retryStreamAt = 0;
  const accept = (value: unknown) => {
    assertRunPoll(value);
    if (
      value.run.id !== initial.id ||
      value.run.conversationId !== initial.conversationId
    )
      throw new ResponseFormatError("返回的任务与当前会话不一致");
    signal.throwIfAborted();
    run = value.run;
    cursor = value.cursor;
    onUpdate(value);
  };
  while (active(run)) {
    signal.throwIfAborted();
    const hidden = typeof document !== "undefined" && document.hidden;
    if (
      api.stream &&
      run.status === "running" &&
      !hidden &&
      Date.now() >= retryStreamAt
    ) {
      let received = false;
      try {
        await api.stream(
          run.id,
          (kind, value) => {
            signal.throwIfAborted();
            if (kind === "snapshot") {
              accept(value);
              received = true;
            } else if (kind === "progress") {
              progress(value);
              if (
                value.runId !== run.id ||
                value.conversationId !== run.conversationId
              )
                throw new ResponseFormatError("实时事件不属于当前会话");
              if (value.cursor <= cursor) return;
              if (value.fromCursor !== cursor)
                throw new ResponseFormatError("实时事件有缺口，正在恢复");
              run = applyAgentEvents(run, value.events);
              cursor = value.cursor;
              onUpdate({ run, cursor, events: value.events });
              received = true;
            } else if (kind === "error") {
              const error = value as { detail?: string; status?: number };
              throw new ApiError(
                error.detail ?? "实时连接中断",
                error.status ?? 503,
              );
            }
          },
          signal,
        );
        if (!active(run)) return;
        if (received) {
          await delay(150, signal);
          continue;
        }
      } catch (error) {
        signal.throwIfAborted();
        if (error instanceof Error && error.name === "AbortError") throw error;
        if (error instanceof ApiError && [401, 403].includes(error.status))
          throw error;
        // Bounded stream slots or older proxies can use the existing read API.
        if (
          !(error instanceof ApiError && [404, 405, 503].includes(error.status))
        )
          onFailure(error);
      }
      retryStreamAt = Date.now() + 5000;
    }
    try {
      accept(await api.poll(run.id, cursor, signal));
    } catch (error) {
      signal.throwIfAborted();
      if (error instanceof Error && error.name === "AbortError") throw error;
      if (error instanceof ApiError && [401, 403, 404].includes(error.status))
        throw error;
      onFailure(error);
      await delay(3000, signal);
      continue;
    }
    if (active(run))
      await delay(hidden ? 3000 : run.status === "queued" ? 1500 : 800, signal);
  }
}
