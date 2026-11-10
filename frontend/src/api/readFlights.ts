/** Share only pending, identical reads. Every consumer owns its cancellation. */
type Flight = {
  controller: AbortController;
  pending: Promise<unknown>;
  consumers: number;
  settled: boolean;
};

export function canonicalReadKey(value: unknown) {
  return JSON.stringify(value, (_key, item) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(
          Object.keys(item)
            .sort()
            .map((key) => [key, item[key]]),
        )
      : item,
  );
}

export function isReadOnlyRequest(method: string, url: string) {
  return (
    ["GET", "HEAD"].includes(method.toUpperCase()) ||
    (method.toUpperCase() === "POST" &&
      (/^\/api\/business-flows\/[1-9]\d*\/prepare-inputs\/$/.test(
        new URL(url, "http://read.invalid").pathname,
      ) ||
        /^\/api\/catalog\/resources\/[1-9]\d*\/(?:query|nongeo-query)\/$/.test(
          new URL(url, "http://read.invalid").pathname,
        )))
  );
}

export class ReadFlights {
  private flights = new Map<string, Flight>();
  private verified = new WeakMap<
    object,
    { scope: string; generation: number; at: number }
  >();
  private generation = 0;
  private absent = new Map<string, { generation: number; at: number }>();

  get revision() {
    return this.generation;
  }
  get pendingCount() {
    return this.flights.size;
  }

  invalidate() {
    this.generation++;
    this.flights.clear();
  }

  markVerified(value: object, scope: string, generation: number) {
    this.absent.delete(scope);
    this.verified.set(value, { scope, generation, at: Date.now() });
  }

  markAbsent(scope: string, generation: number) {
    this.absent.delete(scope);
    this.absent.set(scope, { generation, at: Date.now() });
    while (this.absent.size > 128)
      this.absent.delete(this.absent.keys().next().value!);
  }

  hasFreshAbsence(scope: string, maxAgeMs = 30000) {
    const record = this.absent.get(scope);
    const now = Date.now();
    return Boolean(
      record &&
      record.generation === this.generation &&
      now >= record.at &&
      now - record.at < maxAgeMs,
    );
  }

  isVerified(value: object | undefined, scope: string, maxAgeMs = 30000) {
    const record = value && this.verified.get(value);
    const now = Date.now();
    return Boolean(
      record &&
      record.scope === scope &&
      record.generation === this.generation &&
      now >= record.at &&
      now - record.at < maxAgeMs,
    );
  }

  run<T>(
    key: string,
    load: (signal: AbortSignal) => Promise<T>,
    signal: AbortSignal,
  ): Promise<T> {
    if (signal.aborted) return Promise.reject(signal.reason);
    const identity = `${this.generation}:${key}`;
    let flight = this.flights.get(identity);
    if (!flight) {
      const entry: Flight = {
        controller: new AbortController(),
        consumers: 0,
        settled: false,
        pending: Promise.resolve(),
      };
      entry.pending = Promise.resolve()
        .then(() => {
          entry.controller.signal.throwIfAborted();
          return load(entry.controller.signal);
        })
        .finally(() => {
          entry.settled = true;
          if (this.flights.get(identity) === entry)
            this.flights.delete(identity);
        });
      if (this.flights.size < 128) this.flights.set(identity, entry);
      flight = entry;
    }
    const entry = flight;
    entry.consumers++;
    return new Promise<T>((resolve, reject) => {
      let finished = false;
      const release = () => {
        if (finished) return false;
        finished = true;
        signal.removeEventListener("abort", abort);
        entry.consumers--;
        if (!entry.settled && !entry.consumers) {
          if (this.flights.get(identity) === entry)
            this.flights.delete(identity);
          entry.controller.abort();
        }
        return true;
      };
      const abort = () => {
        if (release()) reject(signal.reason);
      };
      signal.addEventListener("abort", abort, { once: true });
      entry.pending.then(
        (value) => {
          if (release()) {
            try {
              resolve(structuredClone(value) as T);
            } catch (error) {
              reject(error);
            }
          }
        },
        (error) => {
          if (release()) reject(error);
        },
      );
    });
  }
}
