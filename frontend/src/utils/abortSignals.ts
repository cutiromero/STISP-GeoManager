export interface AbortGroup {
  signal: AbortSignal;
  dispose: () => void;
}

/** Combine cancellation without requiring the newer AbortSignal.any API. */
export function combineAbortSignals(signals: AbortSignal[]): AbortGroup {
  const sources = [...new Set(signals)];
  const sole = sources[0];
  if (sources.length === 1 && sole) {
    return { signal: sole, dispose: () => {} };
  }
  if (typeof AbortSignal.any === "function") {
    return { signal: AbortSignal.any(sources), dispose: () => {} };
  }
  const controller = new AbortController();
  const listeners = new Map<AbortSignal, () => void>();
  const dispose = () => {
    for (const [source, listener] of listeners) {
      source.removeEventListener("abort", listener);
    }
    listeners.clear();
  };
  const abort = (source: AbortSignal) => {
    controller.abort(source.reason);
    dispose();
  };
  for (const source of sources) {
    if (source.aborted) {
      abort(source);
      break;
    }
    const listener = () => abort(source);
    listeners.set(source, listener);
    source.addEventListener("abort", listener, { once: true });
  }
  return { signal: controller.signal, dispose };
}
