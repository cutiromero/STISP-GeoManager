import { afterEach, expect, it, vi } from "vitest";
import { runMapDisplayQuery } from "./mapDisplayQuery";

afterEach(() => vi.useRealTimers());

it("serializes display reads instead of occupying multiple server slots", async () => {
  let finish!: () => void;
  const first = runMapDisplayQuery(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    new AbortController().signal,
  );
  const request = vi.fn().mockResolvedValue(2);
  const second = runMapDisplayQuery(request, new AbortController().signal);
  await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
  expect(request).not.toHaveBeenCalled();
  finish();
  await first;
  expect(await second).toBe(2);
});

it("recovers a transient 503 and does not retry permission failures", async () => {
  vi.useFakeTimers();
  const request = vi
    .fn()
    .mockRejectedValueOnce({ status: 503, retryAfterMs: 2000 })
    .mockResolvedValue("ready");
  const pending = runMapDisplayQuery(request, new AbortController().signal);
  await vi.advanceTimersByTimeAsync(1999);
  expect(request).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(await pending).toBe("ready");
  const denied = vi.fn().mockRejectedValue({ status: 403 });
  await expect(
    runMapDisplayQuery(denied, new AbortController().signal),
  ).rejects.toMatchObject({ status: 403 });
  expect(denied).toHaveBeenCalledTimes(1);
});

it("cancels a delayed retry when a map moves or the project changes", async () => {
  vi.useFakeTimers();
  const controller = new AbortController();
  const request = vi.fn().mockRejectedValue({ status: 503 });
  const pending = runMapDisplayQuery(request, controller.signal);
  const assertion = expect(pending).rejects.toMatchObject({
    name: "AbortError",
  });
  await vi.advanceTimersByTimeAsync(0);
  controller.abort();
  await assertion;
  await vi.advanceTimersByTimeAsync(30000);
  expect(request).toHaveBeenCalledTimes(1);
});
