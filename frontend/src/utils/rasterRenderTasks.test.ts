import { afterEach, describe, expect, it, vi } from "vitest";
import {
  RasterRenderTaskRegistry,
  waitForAbortableDelay,
} from "./rasterRenderTasks";

describe("RasterRenderTaskRegistry", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("cancels the previous task for the same layer", () => {
    const registry = new RasterRenderTaskRegistry();
    const first = registry.start("group:layer");
    const second = registry.start("group:layer");

    expect(first.controller.signal.aborted).toBe(true);
    expect(second.controller.signal.aborted).toBe(false);
    expect(registry.isCurrent(first)).toBe(false);
    expect(registry.isCurrent(second)).toBe(true);
  });

  it("marks and aborts a task that exceeds the polling deadline", async () => {
    vi.useFakeTimers();
    const registry = new RasterRenderTaskRegistry(5000);
    const task = registry.start("group:layer");

    await vi.advanceTimersByTimeAsync(5000);

    expect(task.timedOut).toBe(true);
    expect(task.controller.signal.aborted).toBe(true);
    registry.finish(task);
  });

  it("cancels every active layer task during teardown", () => {
    const registry = new RasterRenderTaskRegistry();
    const first = registry.start("group:layer-a");
    const second = registry.start("group:layer-b");

    registry.cancelAll();

    expect(first.controller.signal.aborted).toBe(true);
    expect(second.controller.signal.aborted).toBe(true);
  });

  it("interrupts a pending polling delay on abort", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const pending = waitForAbortableDelay(1000, controller.signal);

    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(vi.getTimerCount()).toBe(0);
  });
});
