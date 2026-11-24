import type { HermesMessage } from "../api/generated";

export type ToolActivity = {
  id: string;
  kind: "tool";
  name: string;
  status: "running" | "done" | "error";
};

export type Activity =
  | ToolActivity
  | { id: string; kind: "commentary" | "reasoning"; text: string };

export type LiveConversation = { activities: Activity[]; answer: string };

export const emptyConversation: LiveConversation = {
  activities: [],
  answer: "",
};

export function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

export function toolPayload(value: unknown) {
  if (typeof value !== "string") return object(value);
  const text = value
    .trim()
    .replace(
      /^<untrusted_tool_result source="[^"]+">\s*([\s\S]*?)\s*<\/untrusted_tool_result>$/,
      "$1",
    );
  try {
    return object(
      JSON.parse(
        text.startsWith("The following content")
          ? text.slice(text.indexOf("\n\n") + 2)
          : text,
      ),
    );
  } catch {
    return {};
  }
}

export function updateConversation(
  previous: LiveConversation,
  event: Record<string, unknown>,
): LiveConversation {
  const { activities, answer } = previous;
  const id = String(event.seq ?? activities.length);
  if (event.event === "message.delta" && typeof event.delta === "string") {
    return { activities, answer: answer + event.delta };
  }
  if (event.event === "message.interim" && typeof event.text === "string") {
    const lastNote = [...activities]
      .reverse()
      .find((activity) => activity.kind === "commentary");
    const alreadyShown =
      lastNote?.kind === "commentary" &&
      lastNote.text.trim() === event.text.trim();
    return {
      activities: alreadyShown
        ? activities
        : [...activities, { id, kind: "commentary", text: event.text }],
      answer: event.already_streamed ? "" : answer,
    };
  }
  if (
    event.event === "reasoning.delta" ||
    event.event === "reasoning.available"
  ) {
    const text = event.event === "reasoning.delta" ? event.delta : event.text;
    if (typeof text !== "string" || !text) return previous;
    const last = activities[activities.length - 1];
    if (last?.kind === "reasoning") {
      if (event.event === "reasoning.available") return previous;
      return {
        answer,
        activities: [
          ...activities.slice(0, -1),
          { ...last, text: last.text + text },
        ],
      };
    }
    return {
      answer,
      activities: [...activities, { id, kind: "reasoning", text }],
    };
  }
  if (event.event === "tool.started" || event.event === "tool.completed") {
    const starting = event.event === "tool.started";
    const name = typeof event.tool === "string" ? event.tool : "";
    const matching =
      typeof event.tool_call_id === "string"
        ? activities.findIndex(
            (item) => item.kind === "tool" && item.id === event.tool_call_id,
          )
        : starting
          ? -1
          : activities
              .map(
                (item) =>
                  item.kind === "tool" &&
                  item.name === name &&
                  item.status === "running",
              )
              .lastIndexOf(true);
    const entry: ToolActivity = {
      id:
        activities[matching]?.id ?? String(event.tool_call_id ?? `tool-${id}`),
      kind: "tool",
      name,
      status: starting ? "running" : event.error ? "error" : "done",
    };
    if (matching >= 0) {
      return {
        answer,
        activities: activities.map((item, index) =>
          index === matching ? entry : item,
        ),
      };
    }
    const note = answer.trim()
      ? [{ id: `note-${id}`, kind: "commentary" as const, text: answer }]
      : [];
    return { activities: [...activities, ...note, entry], answer: "" };
  }
  if (event.event === "replay.truncated") return { activities, answer: "" };
  return previous;
}

export type ConversationTurn = {
  id: number;
  user?: HermesMessage;
  messages: HermesMessage[];
};

export function groupConversation(messages: HermesMessage[]) {
  const turns: ConversationTurn[] = [];
  for (const message of messages) {
    if (message.display_kind === "hidden") continue;
    const turn = turns[turns.length - 1];
    if (message.role === "user") {
      turns.push({ id: message.id, user: message, messages: [] });
    } else if (message.role === "assistant" || message.role === "tool") {
      if (turn) turn.messages.push(message);
      else turns.push({ id: message.id, messages: [message] });
    }
  }
  return turns;
}

export function savedConversation(messages: HermesMessage[]): LiveConversation {
  const lastAnswer = [...messages]
    .reverse()
    .find(
      (message) =>
        message.role === "assistant" &&
        typeof message.content === "string" &&
        message.content.trim() &&
        !message.tool_calls?.length &&
        message.finish_reason !== "tool_calls",
    );
  const final =
    messages[messages.length - 1]?.role === "assistant" &&
    messages[messages.length - 1]?.id === lastAnswer?.id
      ? lastAnswer
      : undefined;
  const activities: Activity[] = [];
  for (const message of messages) {
    if (message.role === "tool") {
      const payload = toolPayload(message.content);
      activities.push({
        id: `message-${message.id}`,
        kind: "tool",
        name: message.tool_name ?? "",
        status: payload.error ? "error" : "done",
      });
      continue;
    }
    if (message.role !== "assistant") continue;
    const reasoning =
      message.reasoning_content?.trim() || message.reasoning?.trim();
    if (reasoning)
      activities.push({
        id: `reasoning-${message.id}`,
        kind: "reasoning",
        text: reasoning,
      });
    if (
      message !== final &&
      typeof message.content === "string" &&
      message.content.trim()
    ) {
      activities.push({
        id: `note-${message.id}`,
        kind: "commentary",
        text: message.content,
      });
    }
  }
  return {
    activities,
    answer: typeof final?.content === "string" ? final.content : "",
  };
}
