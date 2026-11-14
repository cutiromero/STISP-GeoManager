import type {
  ResourceListItem,
  ResourceProfileResponse,
} from "../api/generated/types.gen";
import { api } from "../api/client";
import { browserSessionEpoch } from "../auth/browserSession";
import { getActiveProject, requestScope } from "../projects/session";

const MAX_PROFILES = 24;
const profiles = new Map<string, ResourceProfileResponse>();
let currentScope = "";
export function clearMonitorResourceProfiles() {
  profiles.clear();
  currentScope = "";
}
export async function monitorResourceProfile(
  resource: ResourceListItem,
  signal?: AbortSignal,
) {
  const assertScope = requestScope();
  signal?.throwIfAborted();
  assertScope();
  const scope = `${browserSessionEpoch()}:${getActiveProject()}`;
  if (currentScope !== scope) {
    profiles.clear();
    currentScope = scope;
  }
  const key = `${resource.id}:${resource.updatedAt}`;
  const previous = profiles.get(key);
  if (previous) return previous;
  const value = await api.resourceProfile(resource, { signal });
  signal?.throwIfAborted();
  assertScope();
  if (profiles.size >= MAX_PROFILES)
    profiles.delete(profiles.keys().next().value!);
  profiles.set(key, value);
  return value;
}
