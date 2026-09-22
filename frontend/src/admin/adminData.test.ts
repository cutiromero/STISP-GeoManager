import { describe, expect, it } from "vitest";
import { operationLogsToCsv } from "./data";

describe("operationLogsToCsv", () => {
  it("exports a csv document with stable headers", () => {
    const csv = operationLogsToCsv([
      {
        id: 1,
        occurredAt: "2026-06-05 09:31:42",
        operator: "系统管理员",
        module: "认证授权",
        action: "更新角色权限",
        result: "success",
        ipAddress: "10.12.8.21",
        summary: "为数据管理员角色增加数据导出权限",
      },
    ]);

    expect(csv).toContain("时间,操作用户,模块,动作,结果,IP 地址,摘要");
    expect(csv).toContain("更新角色权限");
    expect(csv).toContain("成功");
  });
});
