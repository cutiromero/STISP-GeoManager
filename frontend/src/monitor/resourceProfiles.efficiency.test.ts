import { beforeEach, expect, it, vi } from "vitest";
import type {
  ResourceListItem,
  ResourceProfileResponse,
} from "../api/generated/types.gen";
import { api } from "../api/client";
import {
  clearMonitorResourceProfiles,
  monitorResourceProfile,
} from "./resourceProfiles";
const scope = vi.hoisted(() => ({ epoch: 0, project: "2" }));
vi.mock("../api/client", () => ({ api: { resourceProfile: vi.fn() } }));
vi.mock("../auth/browserSession", () => ({
  browserSessionEpoch: () => scope.epoch,
}));
vi.mock("../projects/session", () => ({
  getActiveProject: () => scope.project,
  requestScope: () => {
    const key = `${scope.epoch}:${scope.project}`;
    return () => {
      if (key !== `${scope.epoch}:${scope.project}`)
        throw new DOMException("Scope changed", "AbortError");
    };
  },
}));
const resource = {
  id: 7,
  name: "分类成果",
  dataType: "raster",
  updatedAt: "v1",
} as ResourceListItem;
const profile = { resource, raster: { id: 99 } } as ResourceProfileResponse;
beforeEach(() => {
  vi.clearAllMocks();
  clearMonitorResourceProfiles();
  scope.epoch = 0;
  scope.project = "2";
  vi.mocked(api.resourceProfile).mockResolvedValue(profile);
});
it("shares one metadata read between map preparation and export", async () => {
  expect(await monitorResourceProfile(resource)).toBe(profile);
  expect(await monitorResourceProfile(resource)).toBe(profile);
  expect(api.resourceProfile).toHaveBeenCalledTimes(1);
});
it("invalidates metadata when the resource revision changes", async () => {
  await monitorResourceProfile(resource);
  await monitorResourceProfile({ ...resource, updatedAt: "v2" });
  expect(api.resourceProfile).toHaveBeenCalledTimes(2);
});
it.each(["account", "project"])(
  "does not reuse a profile across the %s boundary",
  async (boundary) => {
    await monitorResourceProfile(resource);
    if (boundary === "account") scope.epoch++;
    else scope.project = "3";
    await monitorResourceProfile(resource);
    expect(api.resourceProfile).toHaveBeenCalledTimes(2);
  },
);
it("does not retain an aborted late response", async () => {
  let resolve!: (value: ResourceProfileResponse) => void;
  vi.mocked(api.resourceProfile).mockImplementationOnce(
    () =>
      new Promise((accept) => {
        resolve = accept;
      }),
  );
  const controller = new AbortController();
  const pending = monitorResourceProfile(resource, controller.signal);
  controller.abort();
  resolve(profile);
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  await monitorResourceProfile(resource);
  expect(api.resourceProfile).toHaveBeenCalledTimes(2);
});
