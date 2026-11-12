import { ResponseFormatError } from "./responseDiagnostics";

const MAX_FRAME_CHARACTERS = 16 * 1024 * 1024;
// The server sends a heartbeat every two seconds, including during computation.
export const STREAM_IDLE_MILLISECONDS = 15000;

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
      let timeout: ReturnType<typeof setTimeout> | undefined;
      const stalled = new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(
          () =>
            reject(
              new ResponseFormatError("实时连接长时间无响应，正在恢复进度"),
            ),
          STREAM_IDLE_MILLISECONDS,
        );
      });
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await Promise.race([reader.read(), stalled]);
      } finally {
        clearTimeout(timeout);
      }
      const { done, value } = chunk;
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
