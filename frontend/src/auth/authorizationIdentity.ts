import type { User } from "../types";

/** Ignore display/profile changes; invalidate only identity or authorization. */
export function authorizationIdentity(user: User | null) {
  return user
    ? JSON.stringify([
        user.id,
        [...(user.roles ?? [])].sort(),
        Object.entries(user.permissions ?? {}).sort(([a], [b]) =>
          a < b ? -1 : a > b ? 1 : 0,
        ),
      ])
    : "anonymous";
}
