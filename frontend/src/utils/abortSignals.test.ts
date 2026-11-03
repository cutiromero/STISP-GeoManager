import { afterEach, describe, expect, it, vi } from "vitest";
import { combineAbortSignals } from "./abortSignals";

const originalAny = AbortSignal.any;
afterEach(() => {
  Object.defineProperty(AbortSignal, "any", {
    value: originalAny,
    configurable: true,
  });
  vi.restoreAllMocks();
});

function withoutNativeAny() {
  Object.defineProperty(AbortSignal, "any", {
    value: undefined,
    configurable: true,
  });
}

describe("older browser request cancellation", () => {
  it("combines caller and project cancellation when native any is absent", () => {
    withoutNativeAny();
    const caller = new AbortController();
    const project = new AbortController();
    const group = combineAbortSignals([caller.signal, project.signal]);
    expect(group.signal.aborted).toBe(false);
    project.abort("project changed");
    expect(group.signal.aborted).toBe(true);
    expect(group.signal.reason).toBe("project changed");
  });

  it("removes both listeners after completion without aborting the result", () => {
    withoutNativeAny();
    const caller = new AbortController();
    const project = new AbortController();
    const removeCaller = vi.spyOn(caller.signal, "removeEventListener");
    const removeProject = vi.spyOn(project.signal, "removeEventListener");
    const group = combineAbortSignals([caller.signal, project.signal]);
    group.dispose();
    group.dispose();
    expect(removeCaller).toHaveBeenCalledTimes(1);
    expect(removeProject).toHaveBeenCalledTimes(1);
    project.abort();
    expect(group.signal.aborted).toBe(false);
  });

  it("retains an existing abort reason and releases listeners already attached", () => {
    withoutNativeAny();
    const caller = new AbortController();
    const project = new AbortController();
    const remove = vi.spyOn(caller.signal, "removeEventListener");
    project.abort("already left");
    const group = combineAbortSignals([caller.signal, project.signal]);
    expect(group.signal.aborted).toBe(true);
    expect(group.signal.reason).toBe("already left");
    expect(remove).toHaveBeenCalledTimes(1);
  });
});
