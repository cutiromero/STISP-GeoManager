import { expect, it } from "vitest";
import type { AgentResearchDemoList } from "../api/generated/types.gen";
import { workflowScenarioOptions } from "./WorkflowPanel";

const demos: AgentResearchDemoList["items"] = [
  {
    projectId: 3,
    projectName: "已更名的地质项目",
    scenario: "geology_map_review",
    title: "地质成果智能检查与修正",
    prompt: "检查地图",
    sampleNature: "demonstration_case",
    available: false,
  },
  {
    projectId: 8,
    projectName: "已更名的生态项目",
    scenario: "ecology_investigation",
    title: "干旱区生态风险评估分析决策",
    prompt: "分析变化",
    sampleNature: "synthetic",
    available: true,
  },
];

it("uses stable project IDs and keeps the scene visible when services are offline", () => {
  expect(workflowScenarioOptions("3", demos).map((item) => item.value)).toEqual(
    ["research_processing", "geology_map_review"],
  );
  expect(workflowScenarioOptions("8", demos).map((item) => item.value)).toEqual(
    ["research_processing", "ecology_investigation"],
  );
  expect(workflowScenarioOptions("1", demos).map((item) => item.value)).toEqual(
    ["research_processing"],
  );
});
