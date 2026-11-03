/** Where a signed-in user was when the session ended without an explicit logout. */
const KEY = "auth:expired-return";

function stored(): { path: string; userId: number } | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(KEY) ?? "null");
    return typeof value?.path === "string" &&
      value.path.startsWith("/") &&
      !value.path.startsWith("//") &&
      typeof value.userId === "number"
      ? value
      : null;
  } catch {
    return null;
  }
}

export function markSessionExpired(userId: number) {
  try {
    const path = `${window.location.pathname}${window.location.search}`;
    if (!path.startsWith("/login"))
      sessionStorage.setItem(KEY, JSON.stringify({ path, userId }));
  } catch {
    // Without storage the login page simply shows no notice.
  }
}

export function sessionExpired(): boolean {
  return stored() !== null;
}

/** The saved page, only for the account whose session ended there. */
export function expiredReturnPath(userId: number): string | null {
  const value = stored();
  return value && value.userId === userId ? value.path : null;
}

export function clearSessionExpired() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to clear.
  }
}
