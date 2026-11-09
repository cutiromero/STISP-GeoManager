import { expect, it, vi } from "vitest";
import { consumeServerEvents } from "./eventStream";

const encoder = new TextEncoder();
const response = (stream: ReadableStream<Uint8Array>) =>
  new Response(stream, {
    headers: { "Content-Type": "text/event-stream; charset=utf-8" },
  });

it("delivers real split UTF-8 frames before the response closes", async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(value) {
      controller = value;
    },
  });
  const callback = vi.fn();
  const pending = consumeServerEvents(response(stream), callback);
  const bytes = encoder.encode(
    'event: progress\r\ndata: {"text":"中文🌍"}\r\n\r\n',
  );
  for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
  await vi.waitFor(() =>
    expect(callback).toHaveBeenCalledWith("progress", { text: "中文🌍" }),
  );
  controller.enqueue(
    encoder.encode(': heartbeat\n\nevent: end\ndata: {"reason":"settled"}\n\n'),
  );
  controller.close();
  await pending;
  expect(callback).toHaveBeenCalledTimes(2);
});

it("aborts the underlying stream instead of leaving a reader alive", async () => {
  const cancelled = vi.fn();
  const abort = new AbortController();
  const stream = new ReadableStream<Uint8Array>({ cancel: cancelled });
  const pending = consumeServerEvents(response(stream), vi.fn(), abort.signal);
  abort.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect(cancelled).toHaveBeenCalledOnce();
});

it("does not render incomplete JSON or a partial final frame", async () => {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode('event: progress\ndata: {"partial":'));
      controller.close();
    },
  });
  const callback = vi.fn();
  await expect(
    consumeServerEvents(response(stream), callback),
  ).rejects.toMatchObject({
    name: "ResponseFormatError",
    issue: "实时响应尚未接收完整",
  });
  expect(callback).not.toHaveBeenCalled();
});

it("rejects a buffered HTML response rather than displaying it as model text", async () => {
  await expect(
    consumeServerEvents(new Response("<html>proxy error</html>"), vi.fn()),
  ).rejects.toMatchObject({
    name: "ResponseFormatError",
    issue: "实时响应格式无效",
  });
});
