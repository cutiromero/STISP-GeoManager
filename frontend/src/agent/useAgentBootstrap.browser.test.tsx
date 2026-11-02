import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentBootstrap } from "../api/generated/types.gen";
import { ApiError } from "../api/client";
import type { User } from "../types";
import {
  clearAgentBootstrap,
  useAgentBootstrap,
  useAgentBootstrapState,
} from "./useAgentBootstrap";

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
  it("distinguishes unknown and network failure from denial and recovers by retry", async () => {
    const initial = deferred();
    load.mockReturnValueOnce(initial.promise).mockResolvedValueOnce(granted);
    const view = renderHook(useAgentBootstrapState);
    expect(view.result.current.status).toBe("loading");
    expect(view.result.current.bootstrap).toBeNull();
    await act(async () => initial.reject(new Error("connection lost")));
    expect(view.result.current.status).toBe("error");
    expect(view.result.current.bootstrap).toBeNull();
    await act(async () => view.result.current.retry());
    expect(view.result.current.status).toBe("ready");
    expect(view.result.current.bootstrap).toEqual(granted);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it.each([401, 403])(
    "separates explicit %s rejection from a transient failure",
    async (status) => {
      load.mockRejectedValueOnce(new ApiError("access rejected", status));
      const view = renderHook(useAgentBootstrapState);
      await waitFor(() =>
        expect(view.result.current.status).toBe(
          status === 401 ? "unauthenticated" : "forbidden",
        ),
      );
      expect(view.result.current.bootstrap).toBeNull();
    },
  );

  it.each([409, 503])(
    "keeps confirmed access for %s without reporting a permission denial",
    async (status) => {
      load.mockResolvedValueOnce(granted);
      const view = renderHook(useAgentBootstrapState);
      await waitFor(() => expect(view.result.current.status).toBe("ready"));
      load.mockRejectedValueOnce(new ApiError("service busy", status));
      await act(async () => view.result.current.retry());
      expect(view.result.current.status).toBe("error");
      expect(view.result.current.bootstrap).toEqual(granted);
      load.mockResolvedValueOnce(granted);
      await act(async () => view.result.current.retry());
      expect(view.result.current.status).toBe("ready");
    },
  );

  it("does not poll permissions while the page stays open", async () => {
    vi.useFakeTimers();
    try {
      load.mockResolvedValue(granted);
      const view = renderHook(useAgentBootstrap);
      await act(async () => {});
      expect(view.result.current).toEqual(granted);
      await act(async () => vi.advanceTimersByTimeAsync(90000));
      expect(load).toHaveBeenCalledOnce();
      expect(view.result.current).toEqual(granted);
      view.unmount();
    } finally {
      vi.useRealTimers();
    }
  });

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

  it("retains access after a network failure and clears logout snapshots without restoring late requests", async () => {
    load.mockResolvedValueOnce(granted);
    const first = renderHook(useAgentBootstrap);
    await waitFor(() => expect(first.result.current).toEqual(granted));
    first.unmount();
    const failed = deferred();
    load.mockReturnValueOnce(failed.promise);
    const second = renderHook(useAgentBootstrap);
    expect(second.result.current).toEqual(granted);
    await act(async () => failed.reject(new Error("access check failed")));
    expect(second.result.current).toEqual(granted);
    second.unmount();
    const late = deferred();
    load.mockReturnValueOnce(late.promise);
    const third = renderHook(useAgentBootstrap);
    expect(third.result.current).toEqual(granted);
    third.unmount();
    clearAgentBootstrap(session.user!);
    await act(async () => late.resolve(granted));
    load.mockReturnValueOnce(deferred().promise);
    const fourth = renderHook(useAgentBootstrap);
    expect(fourth.result.current).toBeNull();
  });

  it("does not turn an incomplete response into a permission denial", async () => {
    load.mockResolvedValueOnce(granted);
    const first = renderHook(useAgentBootstrap);
    await waitFor(() => expect(first.result.current).toEqual(granted));
    first.unmount();
    const refresh = deferred();
    load.mockReturnValueOnce(refresh.promise);
    const second = renderHook(useAgentBootstrap);
    await act(async () =>
      refresh.resolve({
        ...granted,
        canAgent: undefined,
      } as unknown as AgentBootstrap),
    );
    expect(second.result.current).toEqual(granted);
  });

  it("does not retain cached access after an explicit authentication rejection", async () => {
    load.mockResolvedValueOnce(granted);
    const first = renderHook(useAgentBootstrap);
    await waitFor(() => expect(first.result.current).toEqual(granted));
    first.unmount();
    const refresh = deferred();
    load.mockReturnValueOnce(refresh.promise);
    const second = renderHook(useAgentBootstrap);
    await act(async () => refresh.reject(new ApiError("权限已撤销", 403)));
    expect(second.result.current).toBeNull();
  });
});
