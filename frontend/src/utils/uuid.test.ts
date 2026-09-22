import { afterEach, describe, expect, it, vi } from "vitest";
import { createUuid } from "./uuid";

describe("createUuid", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("supports browsers that only expose getRandomValues", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(7);
        return bytes;
      },
    });

    const value = createUuid();
    expect(value).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
});
