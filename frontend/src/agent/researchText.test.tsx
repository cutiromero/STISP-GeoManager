import { expect, it } from "vitest";
import { briefTitle, emphasizeNumbers } from "./researchText";

it("titles a long request by its first sentence", () => {
  expect(
    briefTitle(
      "请使用当前项目的海德乌拉演示案例，按综合入口检查岩性。读取知识。",
    ),
  ).toBe("使用当前项目的海德乌拉演示案例，按综合入口检查岩性");
  expect(briefTitle("检查地图", 36)).toBe("检查地图");
  expect(briefTitle("a".repeat(50)).endsWith("…")).toBe(true);
});

it("marks counts in a conclusion", () => {
  const parts = emphasizeNumbers("5 项获批变更已执行，2 项未批准项保留");
  expect(parts.filter((part) => typeof part !== "string")).toHaveLength(2);
});
