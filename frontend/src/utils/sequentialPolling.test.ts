import { afterEach, describe, expect, it, vi } from "vitest";
import { startSequentialPolling } from "./sequentialPolling";

describe("startSequentialPolling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("waits for the active request before scheduling the next one", async () => {
    vi.useFakeTimers();
    let resolveFirst: ((value: boolean) => void) | undefined;
    const task = vi
      .fn<(signal: AbortSignal) => Promise<boolean>>()
      .mockImplementationOnce(
        () =>
          new Promise<boolean>((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValue(false);

    const stop = startSequentialPolling(task, {
      intervalMs: 1000,
      runImmediately: true,
    });

    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(task).toHaveBeenCalledTimes(1);

    resolveFirst?.(true);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(999);
    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(task).toHaveBeenCalledTimes(2);

    stop();
  });

  it("aborts the active request and clears future work when stopped", async () => {
    vi.useFakeTimers();
    let observedSignal: AbortSignal | undefined;
    const task = vi.fn((signal: AbortSignal) => {
      observedSignal = signal;
      return new Promise<boolean>(() => undefined);
    });

    const stop = startSequentialPolling(task, {
      intervalMs: 1000,
      runImmediately: true,
    });
    stop();

    expect(observedSignal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(task).toHaveBeenCalledTimes(1);
  });
});
