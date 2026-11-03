import { describe, expect, it } from "vitest";
import type { Group } from "../types";
import { sortRolesByPermissions } from "./roleOrder";

function group(id: number, name: string, permissions: string[]): Group {
  return {
    id,
    name,
    permissions,
    userCount: 0,
    isProtected: false,
    lockedPermissions: [],
  };
}

describe("role display order", () => {
  it("keeps super administrator first and orders remaining roles by saved permissions", () => {
    const items = [
      group(3, "科研用户", ["read", "export"]),
      group(2, "平台管理员", ["read", "export", "manage"]),
      group(1, "超级管理员", ["root"]),
      group(4, "普通用户", ["read"]),
      group(5, "游客", []),
    ];
    expect(sortRolesByPermissions(items).map((item) => item.name)).toEqual([
      "超级管理员",
      "平台管理员",
      "科研用户",
      "普通用户",
      "游客",
    ]);
    expect(items[0].name).toBe("科研用户");
  });

  it("uses actual unique permissions for custom roles and stable ties", () => {
    const items = [
      group(4, "普通用户", ["read", "read"]),
      group(2, "平台管理员", ["read", "manage"]),
      group(9, "专题管理员", ["read", "manage", "export"]),
      group(8, "科研用户", ["read", "manage"]),
    ];
    expect(sortRolesByPermissions(items).map((item) => item.id)).toEqual([
      9, 2, 8, 4,
    ]);
  });
});
