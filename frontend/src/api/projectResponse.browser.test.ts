import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { platformApi } from "./platform";
import {
  RESPONSE_DIAGNOSTICS_KEY,
  ResponseFormatError,
} from "./responseDiagnostics";

const valid = {
  items: [{ id: 3, name: "逻辑推理", isActive: true, isDefault: false }],
  canManage: false,
  canAssign: false,
  defaultProjectId: 3,
};
const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.removeItem(RESPONSE_DIAGNOSTICS_KEY);
  vi.spyOn(console, "warn").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it.each([undefined, null, {}, [null], [{ id: 3 }]])(
  "rejects malformed project items %j before exposing them to page state",
  async (items) => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...valid, items }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(platformApi.projects()).rejects.toBeInstanceOf(
      ResponseFormatError,
    );
    const records = JSON.parse(
      sessionStorage.getItem(RESPONSE_DIAGNOSTICS_KEY) ?? "[]",
    );
    expect(records[0].requestedUrl).toContain("/api/projects/");
    expect(records[0].issue).toContain("projects.items");
    expect(records[0].structure.fields.items?.type ?? "missing").toBe(
      items === undefined
        ? "missing"
        : items === null
          ? "null"
          : Array.isArray(items)
            ? "array"
            : "object",
    );
  },
);
it("preserves the authorized project response and accepts a real empty list", async () => {
  for (const response of [
    valid,
    { ...valid, items: [], defaultProjectId: null },
  ]) {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(response), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(await platformApi.projects()).toEqual(response);
  }
});
