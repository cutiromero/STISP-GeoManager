import { expect, it } from "vitest";
import { researchDemoLaunch } from "./researchDemoLaunch";

const launch = {
  scenario: "ecology_investigation",
  projectId: 8,
  prompt: "使用模拟资料分析并保存成果",
  token: "launch-token-once",
};
it("accepts only a supported case in the current authorized project", () => {
  expect(researchDemoLaunch(launch, "8")).toEqual(launch);
  expect(
    researchDemoLaunch({ ...launch, scenario: "geology_correction" }, "8"),
  ).toMatchObject({ scenario: "geology_correction" });
});
it("rejects stale cross-project and malformed navigation state", () => {
  for (const value of [
    null,
    "demo",
    {},
    { ...launch, projectId: 1 },
    { ...launch, scenario: "run_anything" },
    { ...launch, token: "x" },
    { ...launch, prompt: " " },
  ]) {
    expect(researchDemoLaunch(value, "8")).toBeNull();
  }
});
