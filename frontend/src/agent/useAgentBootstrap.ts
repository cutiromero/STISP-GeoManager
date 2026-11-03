import { useEffect, useState } from "react";
import { agentApi } from "../api/agent";
import { ApiError } from "../api/client";
import type { AgentBootstrap } from "../api/generated/types.gen";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import type { User } from "../types";

type BootstrapEntry = {
  value: AgentBootstrap | null;
  pending: Promise<AgentBootstrap> | null;
};
export type AgentBootstrapStatus =
  | "loading"
  | "ready"
  | "error"
  | "unauthenticated"
  | "forbidden";
type BootstrapSnapshot = {
  user: User | null;
  scope: string;
  value: AgentBootstrap | null;
  status: AgentBootstrapStatus;
  error: string;
};
const snapshots = new WeakMap<User, Map<string, BootstrapEntry>>();

export function clearAgentBootstrap(user: User) {
  snapshots.delete(user);
}

function loadBootstrap(user: User, scope: string) {
  let scopes = snapshots.get(user);
  if (!scopes) {
    scopes = new Map();
    snapshots.set(user, scopes);
  }
  let entry = scopes.get(scope);
  if (!entry) {
    entry = { value: null, pending: null };
    scopes.set(scope, entry);
  }
  if (entry.pending) return entry.pending;
  const currentEntry = entry;
  currentEntry.pending = agentApi
    .bootstrap()
    .then((value) => {
      if (
        typeof value?.canChat !== "boolean" ||
        typeof value?.canAgent !== "boolean" ||
        !Array.isArray(value?.models) ||
        value.models.some(
          (model) =>
            !model ||
            typeof model.alias !== "string" ||
            typeof model.status !== "string",
        ) ||
        (value.budgets?.enabled && !Array.isArray(value.budgets.profiles))
      ) {
        throw new Error("智能体配置返回不完整，请重试连接");
      }
      if (snapshots.get(user)?.get(scope) === currentEntry) {
        currentEntry.value = value;
        currentEntry.pending = null;
      }
      return value;
    })
    .catch((error: unknown) => {
      if (snapshots.get(user)?.get(scope) === currentEntry) {
        currentEntry.pending = null;
        if (
          error instanceof ApiError &&
          (error.status === 401 || error.status === 403)
        ) {
          snapshots.get(user)?.delete(scope);
        }
      }
      throw error;
    });
  return currentEntry.pending;
}

export function useAgentBootstrapState() {
  const { user } = useAppContext();
  const project = useProjectContext()?.current;
  const eligible = Boolean(
    user && user.username !== "guest" && !user.roles.includes("游客"),
  );
  const scope = JSON.stringify([project ?? "", user?.roles, user?.permissions]);
  const cached =
    user && eligible ? (snapshots.get(user)?.get(scope)?.value ?? null) : null;
  const [attempt, setAttempt] = useState(0);
  const [snapshot, setSnapshot] = useState<BootstrapSnapshot>({
    user,
    scope,
    value: cached,
    status: cached ? "ready" : "loading",
    error: "",
  });
  useEffect(() => {
    let disposed = false;
    if (!user || !eligible) {
      if (user) clearAgentBootstrap(user);
      return;
    }
    setSnapshot({
      user,
      scope,
      value: snapshots.get(user)?.get(scope)?.value ?? null,
      status: "loading",
      error: "",
    });
    const load = async () => {
      try {
        const result = await loadBootstrap(user, scope);
        if (!disposed)
          setSnapshot({
            user,
            scope,
            value: result,
            status: "ready",
            error: "",
          });
      } catch (error) {
        if (!disposed) {
          setSnapshot({
            user,
            scope,
            value: snapshots.get(user)?.get(scope)?.value ?? null,
            status:
              error instanceof ApiError && error.status === 401
                ? "unauthenticated"
                : error instanceof ApiError && error.status === 403
                  ? "forbidden"
                  : "error",
            error:
              error instanceof Error ? error.message : "智能体连接失败，请重试",
          });
        }
      }
    };
    void load();
    return () => {
      disposed = true;
    };
  }, [user, scope, eligible, attempt]);
  const current = snapshot.user === user && snapshot.scope === scope;
  return {
    bootstrap: eligible ? (current ? snapshot.value : cached) : null,
    status: !user
      ? ("unauthenticated" as const)
      : !eligible
        ? ("forbidden" as const)
        : current
          ? snapshot.status
          : ("loading" as const),
    error: current ? snapshot.error : "",
    retry: () => setAttempt((value) => value + 1),
  };
}

export function useAgentBootstrap() {
  return useAgentBootstrapState().bootstrap;
}
