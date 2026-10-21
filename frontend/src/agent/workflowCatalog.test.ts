import { afterEach, expect, it, vi } from "vitest";
import { allWorkflowPages, workflowGeologyVersions } from "./workflowCatalog";
import { resetProjectSession, setActiveProject } from "../projects/session";
import type {
  ComputeAlgorithm,
  ComputeVersion,
} from "../api/generated/types.gen";

afterEach(() => resetProjectSession());

it("reads every catalog page and rejects repeated incomplete pages", async () => {
  setActiveProject("3");
  const load = vi
    .fn()
    .mockResolvedValueOnce({ items: [{ id: 1 }], total: 2 })
    .mockResolvedValueOnce({ items: [{ id: 2 }], total: 2 });
  expect(
    await allWorkflowPages(load, "3", new AbortController().signal),
  ).toEqual([{ id: 1 }, { id: 2 }]);
  expect(load).toHaveBeenNthCalledWith(2, { page: 2, pageSize: 100 });
  const repeated = vi.fn().mockResolvedValue({ items: [{ id: 1 }], total: 2 });
  await expect(
    allWorkflowPages(repeated, "3", new AbortController().signal),
  ).rejects.toThrow("分页不完整");
});

it("does not request another page after project identity changes or its original signal aborts", async () => {
  setActiveProject("3");
  const load = vi.fn().mockImplementation(async () => {
    setActiveProject("4");
    return { items: [{ id: 1 }], total: 2 };
  });
  await expect(
    allWorkflowPages(load, "3", new AbortController().signal),
  ).rejects.toThrow("项目已切换");
  expect(load).toHaveBeenCalledTimes(1);
  setActiveProject("3");
  const controller = new AbortController();
  controller.abort();
  const untouched = vi.fn();
  await expect(
    allWorkflowPages(untouched, "3", controller.signal),
  ).rejects.toThrow("项目已切换");
  expect(untouched).not.toHaveBeenCalled();
});

it("selects the latest enabled published agent version by created time then ID across same identifiers", () => {
  const version = (
    id: number,
    createdAt: string,
    enabled = true,
  ): ComputeVersion => ({
    id,
    createdAt,
    version: `1.0.${id}`,
    status: "published",
    checksum: "checksum",
    validated: true,
    runtimeDigest: "digest",
    manifest: {
      schemaVersion: 1,
      identifier: "geology-map-check",
      name: "检查",
      version: `1.0.${id}`,
      description: "检查",
      author: "STISP",
      runtime: "geospatial",
      inputs: [],
      parameters: [],
      outputs: [],
      timeoutSeconds: 300,
      deterministic: true,
      agent: { enabled },
    },
  });
  const algorithm = (
    id: number,
    versions: ComputeVersion[],
    enabled = true,
  ): ComputeAlgorithm => ({
    id,
    versions,
    enabled,
    identifier: "geology-map-check",
    name: "检查",
    projectTagId: 3,
    description: "",
    author: "STISP",
    category: "",
    canManage: false,
  });
  const result = workflowGeologyVersions(
    [
      algorithm(1, [version(99, "2026-10-01T00:00:00Z")]),
      algorithm(2, [
        version(2, "2026-10-02T00:00:00Z"),
        version(3, "2026-10-02T00:00:00Z"),
        version(4, "2026-10-03T00:00:00Z", false),
      ]),
      algorithm(3, [version(100, "2026-10-04T00:00:00Z")], false),
    ],
    ["geology-map-check"],
  );
  expect(result.map((item) => item.id)).toEqual([3]);
});
