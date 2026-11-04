import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  collectPageDiagnostics,
  PAGE_ERROR_KEY,
  recordPageError,
} from "./pageDiagnostics";
import { RESPONSE_DIAGNOSTICS_KEY } from "../api/responseDiagnostics";

beforeEach(() => {
  sessionStorage.removeItem(PAGE_ERROR_KEY);
  sessionStorage.removeItem("platform:page-errors");
  sessionStorage.removeItem(RESPONSE_DIAGNOSTICS_KEY);
});
afterEach(() => vi.restoreAllMocks());

it("exports actual stacks, build version and response structure while redacting URL query values", () => {
  const error = new TypeError(
    "Cannot read properties of undefined (reading 'find')",
  );
  error.stack =
    "at f (https://private:password@example.com/AgentPage-hash.js?token=secret:2:15)";
  recordPageError(
    error,
    "at ResearchIntentCard",
    "/agent/workbench?token=secret",
  );
  sessionStorage.setItem(
    RESPONSE_DIAGNOSTICS_KEY,
    JSON.stringify([
      {
        status: 200,
        contentType: "application/json",
        structure: { type: "object", fields: {} },
      },
    ]),
  );
  const result = collectPageDiagnostics();
  const page = result.pageError as Record<string, unknown>;
  expect(page.message).toContain("reading 'find'");
  expect(page.componentStack).toBe("at ResearchIntentCard");
  expect(page.path).toBe("/agent/workbench");
  expect(page.version).toBe(result.version);
  expect(page.stack).toContain("https://example.com/AgentPage-hash.js");
  expect(JSON.stringify(result)).not.toContain("password");
  expect(JSON.stringify(result)).not.toContain("secret");
  expect(result.apiResponseErrors).toHaveLength(1);
});

it("keeps up to five page failures and remains exportable if storage is blocked", () => {
  for (let index = 0; index < 8; index++)
    recordPageError(new Error(`failure ${index}`));
  expect(collectPageDiagnostics().recentPageErrors).toHaveLength(5);
  expect(collectPageDiagnostics().recentPageErrors[0].message).toBe(
    "failure 3",
  );
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(() => recordPageError(new Error("visible failure"))).not.toThrow();
  expect(
    (
      collectPageDiagnostics(new Error("visible failure")).pageError as Record<
        string,
        unknown
      >
    ).message,
  ).toBe("visible failure");
});
