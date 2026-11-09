import { ResponseFormatError } from "./responseDiagnostics";

const MAX_FRAME_CHARACTERS = 16 * 1024 * 1024;

export async function consumeServerEvents(
  response: Response,
  onEvent: (kind: string, data: unknown) => void,
  signal?: AbortSignal,
) {
  if (
    !response.body ||
    !response.headers.get("Content-Type")?.includes("text/event-stream")
  ) {
    await response.body?.cancel().catch(() => {});
    throw new ResponseFormatError("实时响应格式无效");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  const abort = () => void reader.cancel();
  signal?.addEventListener("abort", abort, { once: true });
  try {
    while (true) {
      signal?.throwIfAborted();
      const { done, value } = await reader.read();
      signal?.throwIfAborted();
      buffer += done
        ? decoder.decode()
        : decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        if (boundary > MAX_FRAME_CHARACTERS)
          throw new ResponseFormatError("实时响应超过单条消息上限");
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let kind = "message";
        const data: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) kind = line.slice(6).trim();
          if (line.startsWith("data:"))
            data.push(line.slice(5).replace(/^ /, ""));
        }
        if (data.length) onEvent(kind, JSON.parse(data.join("\n")));
      }
      if (buffer.length > MAX_FRAME_CHARACTERS)
        throw new ResponseFormatError("实时响应超过单条消息上限");
      if (done) {
        if (buffer.trim())
          throw new ResponseFormatError("实时响应尚未接收完整");
        return;
      }
    }
  } finally {
    signal?.removeEventListener("abort", abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
