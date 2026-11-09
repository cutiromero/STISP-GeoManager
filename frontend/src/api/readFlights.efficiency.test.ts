import { describe, expect, it, vi } from "vitest";
import {
  canonicalReadKey,
  isReadOnlyRequest,
  ReadFlights,
} from "./readFlights";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const signal = () => new AbortController().signal;

describe("efficiency: shared read ownership", () => {
  it("sends one read for simultaneous consumers and returns isolated DTOs", async () => {
    const reads = new ReadFlights(),
      pending = deferred<{ fields: string[] }>();
    const load = vi.fn(() => pending.promise);
    const first = reads.run("project:3:resource:585:v1", load, signal());
    const second = reads.run("project:3:resource:585:v1", load, signal());
    await Promise.resolve();
    expect(load).toHaveBeenCalledTimes(1);
    pending.resolve({ fields: ["name"] });
    const [a, b] = await Promise.all([first, second]);
    a.fields.push("local");
    expect(b.fields).toEqual(["name"]);
    expect(reads.pendingCount).toBe(0);
    await reads.run("project:3:resource:585:v1", load, signal());
    expect(load).toHaveBeenCalledTimes(2); // No completed-response permission cache.
  });

  it("does not abort another consumer's work", async () => {
    const reads = new ReadFlights(),
      pending = deferred<number>();
    let wire!: AbortSignal;
    const load = vi.fn((value: AbortSignal) => {
      wire = value;
      return pending.promise;
    });
    const controller = new AbortController();
    const cancelled = reads.run("same", load, controller.signal);
    const kept = reads.run("same", load, signal());
    await Promise.resolve();
    controller.abort();
    await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    expect(wire.aborted).toBe(false);
    pending.resolve(7);
    expect(await kept).toBe(7);
  });

  it("cancels the wire when all consumers leave and permits an immediate retry", async () => {
    const reads = new ReadFlights(),
      pending = deferred<number>();
    let wire!: AbortSignal;
    const controller = new AbortController();
    const old = reads.run(
      "same",
      (value) => {
        wire = value;
        return pending.promise;
      },
      controller.signal,
    );
    await Promise.resolve();
    controller.abort();
    await expect(old).rejects.toMatchObject({ name: "AbortError" });
    expect(wire.aborted).toBe(true);
    const retry = deferred<number>();
    const newer = reads.run("same", () => retry.promise, signal());
    pending.resolve(1);
    await Promise.resolve();
    await Promise.resolve();
    expect(reads.pendingCount).toBe(1);
    retry.resolve(2);
    expect(await newer).toBe(2);
  });

  it("keeps project, login epoch, versions and parameters separate", async () => {
    const reads = new ReadFlights(),
      pending = deferred<number>();
    const load = vi.fn(() => pending.promise);
    const identities = [
      [3, 1, "v1", 100],
      [4, 1, "v1", 100],
      [3, 2, "v1", 100],
      [3, 1, "v2", 100],
      [3, 1, "v1", 200],
    ];
    const calls = identities.map((identity) =>
      reads.run(canonicalReadKey(identity), load, signal()),
    );
    await Promise.resolve();
    expect(load).toHaveBeenCalledTimes(5);
    pending.resolve(1);
    await Promise.all(calls);
    expect(canonicalReadKey({ b: 2, a: 1 })).toBe(
      canonicalReadKey({ a: 1, b: 2 }),
    );
  });

  it("invalidates pending-read sharing at write boundaries without breaking existing callers", async () => {
    const reads = new ReadFlights(),
      old = deferred<number>(),
      current = deferred<number>();
    const first = reads.run("same", () => old.promise, signal());
    reads.invalidate();
    const second = reads.run("same", () => current.promise, signal());
    old.resolve(1);
    expect(await first).toBe(1);
    expect(reads.pendingCount).toBe(1);
    current.resolve(2);
    expect(await second).toBe(2);
  });

  it("does not retain errors", async () => {
    const reads = new ReadFlights(),
      failure = new Error("temporary");
    await expect(
      reads.run("same", () => Promise.reject(failure), signal()),
    ).rejects.toBe(failure);
    expect(await reads.run("same", () => Promise.resolve(3), signal())).toBe(3);
  });

  it("reuses only a fresh, session-bound descriptor, not serialized metadata", () => {
    const reads = new ReadFlights(),
      preview = {};
    reads.markVerified(preview, "login:1:project:3", reads.revision);
    expect(reads.isVerified(preview, "login:1:project:3")).toBe(true);
    expect(reads.isVerified({}, "login:1:project:3")).toBe(false);
    expect(reads.isVerified(preview, "login:2:project:3")).toBe(false);
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 30001);
    expect(reads.isVerified(preview, "login:1:project:3")).toBe(false);
    vi.restoreAllMocks();
    reads.invalidate();
    expect(reads.isVerified(preview, "login:1:project:3")).toBe(false);
  });

  it("excludes mutations from read sharing", () => {
    expect(isReadOnlyRequest("POST", "/api/catalog/resources/585/query/")).toBe(
      true,
    );
    expect(isReadOnlyRequest("PATCH", "/api/admin/data-resources/585/")).toBe(
      false,
    );
    expect(
      isReadOnlyRequest("POST", "/api/catalog/resources/bulk-delete/"),
    ).toBe(false);
    expect(isReadOnlyRequest("POST", "/api/agent/conversations/1/runs/")).toBe(
      false,
    );
  });

  it("remembers missing tile readiness briefly without caching an authorization result", () => {
    const reads = new ReadFlights();
    reads.markAbsent("login:1:project:3:resource:585:v1", reads.revision);
    expect(reads.hasFreshAbsence("login:1:project:3:resource:585:v1")).toBe(
      true,
    );
    expect(reads.hasFreshAbsence("login:1:project:4:resource:585:v1")).toBe(
      false,
    );
    reads.invalidate();
    expect(reads.hasFreshAbsence("login:1:project:3:resource:585:v1")).toBe(
      false,
    );
  });
});
