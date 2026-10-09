import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentBootstrap } from "../api/generated/types.gen";
import type { User } from "../types";
import { clearAgentBootstrap, useAgentBootstrap } from "./useAgentBootstrap";

const { load, session } = vi.hoisted(() => ({
  load: vi.fn(),
  session: { user: null as User | null, project: "1" },
}));
vi.mock("../api/agent", () => ({ agentApi: { bootstrap: load } }));
vi.mock("../contexts/AppContext", () => ({ useAppContext: () => session }));
vi.mock("../projects/ProjectContext", () => ({
  useProjectContext: () => ({ current: session.project }),
}));

const granted: AgentBootstrap = {
  canChat: true,
  canAgent: true,
  canManage: false,
  internetEnabled: false,
  allowAttachments: false,
  workerOnline: true,
  models: [],
  defaultChatModel: "model",
  defaultAgentModel: "model",
  capabilities: [],
};
const denied = { ...granted, canChat: false, canAgent: false };
function deferred() {
  let resolve!: (value: AgentBootstrap) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<AgentBootstrap>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  session.user = {
    id: 70,
    username: "researcher",
    roles: ["科研用户"],
    permissions: {},
  } as User;
  session.project = "1";
  load.mockReset();
});

describe("agent capability snapshots", () => {
  it("retains confirmed access across page remounts while refreshing and applies revocation", async () => {
    load.mockResolvedValueOnce(granted);
    const first = renderHook(useAgentBootstrap);
    await waitFor(() => expect(first.result.current).toEqual(granted));
    first.unmount();
    const refresh = deferred();
    load.mockReturnValueOnce(refresh.promise);
    const second = renderHook(useAgentBootstrap);
    expect(second.result.current).toEqual(granted);
    await act(async () => refresh.resolve(denied));
    expect(second.result.current).toEqual(denied);
  });

  it("deduplicates simultaneous header and page checks", async () => {
    const response = deferred();
    load.mockReturnValue(response.promise);
    const header = renderHook(useAgentBootstrap);
    const page = renderHook(useAgentBootstrap);
    expect(header.result.current).toBeNull();
    expect(page.result.current).toBeNull();
    expect(load).toHaveBeenCalledOnce();
    await act(async () => response.resolve(granted));
    expect(header.result.current).toEqual(granted);
    expect(page.result.current).toEqual(granted);
  });

  it("isolates project changes immediately and ignores late results from the old project", async () => {
    const oldProject = deferred();
    const newProject = deferred();
    load
      .mockReturnValueOnce(oldProject.promise)
      .mockReturnValueOnce(newProject.promise);
    const view = renderHook(useAgentBootstrap);
    session.project = "2";
    view.rerender();
    expect(view.result.current).toBeNull();
    await act(async () => oldProject.resolve(granted));
    expect(view.result.current).toBeNull();
    await act(async () => newProject.resolve(denied));
    expect(view.result.current).toEqual(denied);
  });

  it("does not reuse a same-ID login or an outdated role and permission signature", async () => {
    load.mockResolvedValueOnce(granted);
    const view = renderHook(useAgentBootstrap);
    await waitFor(() => expect(view.result.current).toEqual(granted));
    const relogin = deferred();
    load.mockReturnValueOnce(relogin.promise);
    session.user = { ...session.user! };
    view.rerender();
    expect(view.result.current).toBeNull();
    await act(async () => relogin.resolve(granted));
    const changedPermissions = deferred();
    load.mockReturnValueOnce(changedPermissions.promise);
    session.user.permissions.canAccessAdmin = true;
    view.rerender();
    expect(view.result.current).toBeNull();
    await act(async () => changedPermissions.resolve(denied));
    expect(view.result.current).toEqual(denied);
  });

  it("drops failed refreshes and clears logout snapshots without restoring late requests", async () => {
    load.mockResolvedValueOnce(granted);
    const first = renderHook(useAgentBootstrap);
    await waitFor(() => expect(first.result.current).toEqual(granted));
    first.unmount();
    const failed = deferred();
    load.mockReturnValueOnce(failed.promise);
    const second = renderHook(useAgentBootstrap);
    expect(second.result.current).toEqual(granted);
    await act(async () => failed.reject(new Error("access check failed")));
    expect(second.result.current).toBeNull();
    second.unmount();
    const late = deferred();
    load.mockReturnValueOnce(late.promise);
    const third = renderHook(useAgentBootstrap);
    expect(third.result.current).toBeNull();
    third.unmount();
    clearAgentBootstrap(session.user!);
    await act(async () => late.resolve(granted));
    load.mockReturnValueOnce(deferred().promise);
    const fourth = renderHook(useAgentBootstrap);
    expect(fourth.result.current).toBeNull();
  });
});
