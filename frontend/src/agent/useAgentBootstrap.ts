import { useEffect, useState } from "react";
import { agentApi } from "../api/agent";
import type { AgentBootstrap } from "../api/generated/types.gen";
import { useAppContext } from "../contexts/AppContext";
import { useProjectContext } from "../projects/ProjectContext";
import type { User } from "../types";

type BootstrapEntry = {
  value: AgentBootstrap | null;
  pending: Promise<AgentBootstrap> | null;
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
  currentEntry.pending = agentApi.bootstrap().then(
    (value) => {
      if (snapshots.get(user)?.get(scope) === currentEntry) {
        currentEntry.value = value;
        currentEntry.pending = null;
      }
      return value;
    },
    (error: unknown) => {
      if (snapshots.get(user)?.get(scope) === currentEntry) {
        snapshots.get(user)?.delete(scope);
      }
      throw error;
    },
  );
  return currentEntry.pending;
}

export function useAgentBootstrap() {
  const { user } = useAppContext();
  const project = useProjectContext()?.current;
  const eligible = Boolean(
    user && user.username !== "guest" && !user.roles.includes("游客"),
  );
  const scope = JSON.stringify([project ?? "", user?.roles, user?.permissions]);
  const cached =
    user && eligible ? (snapshots.get(user)?.get(scope)?.value ?? null) : null;
  const [snapshot, setSnapshot] = useState({ user, scope, value: cached });
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (!user || !eligible) {
      if (user) clearAgentBootstrap(user);
      return;
    }
    setSnapshot({
      user,
      scope,
      value: snapshots.get(user)?.get(scope)?.value ?? null,
    });
    const load = async () => {
      try {
        const result = await loadBootstrap(user, scope);
        if (!disposed) setSnapshot({ user, scope, value: result });
      } catch {
        if (!disposed) setSnapshot({ user, scope, value: null });
      }
      if (!disposed) timer = setTimeout(load, 30000);
    };
    void load();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [user, scope, eligible]);
  if (!eligible) return null;
  return snapshot.user === user && snapshot.scope === scope
    ? snapshot.value
    : cached;
}
