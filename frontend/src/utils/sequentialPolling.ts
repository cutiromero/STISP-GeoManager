export interface SequentialPollingOptions {
  intervalMs: number;
  runImmediately?: boolean;
  onError?: (error: unknown) => void;
}

export type SequentialPollingTask = (
  signal: AbortSignal,
) => Promise<boolean | void>;

export function startSequentialPolling(
  task: SequentialPollingTask,
  options: SequentialPollingOptions,
): () => void {
  const controller = new AbortController();
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const stop = () => {
    if (stopped) return;
    stopped = true;
    controller.abort();
    if (timeoutId !== null) {
      globalThis.clearTimeout(timeoutId);
      timeoutId = null;
    }
  };

  const schedule = () => {
    if (stopped) return;
    timeoutId = globalThis.setTimeout(() => {
      timeoutId = null;
      void run();
    }, options.intervalMs);
  };

  const run = async () => {
    if (stopped) return;
    try {
      const shouldContinue = await task(controller.signal);
      if (shouldContinue === false) {
        stop();
        return;
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        options.onError?.(error);
      }
      stop();
      return;
    }
    schedule();
  };

  if (options.runImmediately) {
    void run();
  } else {
    schedule();
  }

  return stop;
}
