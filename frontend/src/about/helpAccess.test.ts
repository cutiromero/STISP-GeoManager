import { expect, it } from "vitest";
import type { User } from "../types";
import { canReadHelp } from "./helpAccess";
it("filters administrator and unavailable workflow help for ordinary and research users", () => {
  for (const role of ["普通用户", "科研用户"]) {
    const user = {
      roles: [role],
      permissions: { canQueryData: true, canUploadData: role === "科研用户" },
    } as User;
    expect(canReadHelp("admin-management", user)).toBe(false);
    expect(canReadHelp("permission-audit", user)).toBe(false);
    expect(canReadHelp("backup-security", user)).toBe(false);
    expect(canReadHelp("data-import", user)).toBe(role === "科研用户");
    expect(canReadHelp("spatial-query", user)).toBe(true);
  }
});
