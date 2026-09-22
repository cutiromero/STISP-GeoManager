export const rasterRenderPollTimeoutMs = 120_000;

export interface RasterRenderTask {
  readonly key: string;
  readonly controller: AbortController;
  timedOut: boolean;
}

interface ManagedRasterRenderTask extends RasterRenderTask {
  timeoutId: ReturnType<typeof setTimeout> | null;
}

export class RasterRenderTaskRegistry {
  private readonly tasks = new Map<string, ManagedRasterRenderTask>();

  constructor(private readonly timeoutMs = rasterRenderPollTimeoutMs) {}

  start(key: string): RasterRenderTask {
    this.cancel(key);
    const task: ManagedRasterRenderTask = {
      key,
      controller: new AbortController(),
      timedOut: false,
      timeoutId: null,
    };
    task.timeoutId = globalThis.setTimeout(() => {
      if (this.tasks.get(key) !== task) return;
      task.timedOut = true;
      task.controller.abort();
    }, this.timeoutMs);
    this.tasks.set(key, task);
    return task;
  }

  isCurrent(task: RasterRenderTask): boolean {
    return this.tasks.get(task.key) === task;
  }

  finish(task: RasterRenderTask): void {
    const managed = task as ManagedRasterRenderTask;
    if (managed.timeoutId !== null) {
      globalThis.clearTimeout(managed.timeoutId);
      managed.timeoutId = null;
    }
    if (this.tasks.get(task.key) === task) {
      this.tasks.delete(task.key);
    }
  }

  cancel(key: string): void {
    const task = this.tasks.get(key);
    if (!task) return;
    this.tasks.delete(key);
    if (task.timeoutId !== null) {
      globalThis.clearTimeout(task.timeoutId);
      task.timeoutId = null;
    }
    task.controller.abort();
  }

  cancelAll(): void {
    for (const key of this.tasks.keys()) {
      this.cancel(key);
    }
  }
}

export function waitForAbortableDelay(
  delayMs: number,
  signal: AbortSignal,
): Promise<void> {
  if (signal.aborted) {
    return Promise.reject(createAbortError());
  }
  return new Promise((resolve, reject) => {
    const timeoutId = globalThis.setTimeout(finish, delayMs);
    const handleAbort = () => finish(createAbortError());
    function finish(error?: Error) {
      globalThis.clearTimeout(timeoutId);
      signal.removeEventListener("abort", handleAbort);
      if (error) reject(error);
      else resolve();
    }
    signal.addEventListener("abort", handleAbort, { once: true });
  });
}

export function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

function createAbortError() {
  return new DOMException("栅格渲染任务已取消", "AbortError");
}
