/** Serialize display reads per page; transient overload never replays mutations. */
let tail: Promise<unknown> = Promise.resolve();
const MAX_RETRIES = 4;

function cancelled(signal: AbortSignal) {
  if (signal.aborted)
    throw signal.reason ?? new DOMException("地图查询已取消", "AbortError");
}

function delay(ms: number, signal: AbortSignal) {
  cancelled(signal);
  return new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason ?? new DOMException("地图查询已取消", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}

export function runMapDisplayQuery<T>(
  request: () => Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  const pending = tail
    .catch(() => {})
    .then(async () => {
      for (let attempt = 0; ; attempt++) {
        cancelled(signal);
        try {
          return await request();
        } catch (error) {
          cancelled(signal);
          const failure = error as { status?: number; retryAfterMs?: number };
          if (failure?.status !== 503 || attempt >= MAX_RETRIES) throw error;
          await delay(
            Math.min(
              8000,
              Math.max(failure.retryAfterMs ?? 0, 2000 * 2 ** attempt),
            ),
            signal,
          );
        }
      }
    });
  tail = pending.catch(() => {});
  return pending;
}
